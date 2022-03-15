#include "embedded/flash.h"
#include "embedded/main.h"
#include "embedded/logger.h"
#include "embedded/timer.h"
#include "embedded/client.h"
#include "moatbus/crc.h"

#include <stm32f1xx_hal.h>
#include <sys/unistd.h>
#include <cstdlib>
#include <cstring>

extern struct flash_hdr AppHdr;
extern u_int8_t BootFLASHstart, BootFLASHend;
extern u_int8_t BootRAMstart;
extern u_int8_t AppRAMstart, AppRAMend;
extern char LD_MAX_SIZE;

#define AppFLASHsize (((u_int32_t)&LD_MAX_SIZE)-(((u_int32_t)&AppHdr)-((u_int32_t)&BootFLASHstart)))
#define AppFLASHblocks (AppFLASHsize/FLASH_BLOCK)
static inline void* block2addr(u_int16_t n) {
    return (void *)((u_int32_t)&AppHdr + n*FLASH_BLOCK);
}
static void setup_flash_nocheck();

static MTICK flash_start_mtimer NO_INIT;
static bool run_flash_start(MTICK mt) {
    free(mt);
    flash_start_mtimer = NULL;
    setup_flash_nocheck();
    return false;
}

bool flash_erase(void *start, u_int32_t len)
{
    u_int32_t error = 0;
    if(((u_int32_t)start) & (FLASH_PAGE_SIZE-1))
        return false;
    HAL_FLASH_Unlock();

    FLASH_EraseInitTypeDef FLASH_EraseInitStruct =
    {
    	.TypeErase = FLASH_TYPEERASE_PAGES,
        .Banks = 0,
	//.Sector = ((u_int32_t)start - (u_int32_t)&AppBOOTstart) / FLASH_PAGE_SIZE,
        .PageAddress = (u_int32_t)start,
	//.NbSectors = (len / FLASH_PAGE_SIZE +1,
	.NbPages = (len-1) / FLASH_PAGE_SIZE +1,
    };
    HAL_FLASHEx_Erase(&FLASH_EraseInitStruct,&error);
    
    HAL_FLASH_Lock();
    return false;
}

bool flash_write(void *pos, u_int8_t *data, u_int16_t len)
{
    if(HAL_FLASH_Unlock() != HAL_OK)
        goto err2;
    if (len & 3)
        goto err;
    while(len >= 4) {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, (u_int32_t)pos, *data) != HAL_OK) {
            logger("No write word at x%x", pos);
            goto err;
        }
        pos = (void *)(((u_int32_t *)pos) + 1);
        data += 4;
        len -= 4;
    }
    if (len)
        goto err;
    HAL_FLASH_Lock();
    return true;
err:
    HAL_FLASH_Lock();
err2:
    __enable_irq();
    return false;
}

// struct flash_hdr;
// typedef bool (flash_start_proc)(struct flash_hdr *);
// typedef char flash_process_proc(BusMessage msg);
// typedef void flash_loop_proc();


// struct flash_hdr {
//     u_int32_t magic;
//     u_int32_t crc;
//     u_int16_t len;  // in FLASH_BLOCK blocks
//     u_int16_t version;
//     flash_start_proc *setup;
//     flash_process_proc *process;
//     flash_loop_proc *loop;
//     flash_stop_proc *stop;
//     u_int8_t data[0];
// };


u_int32_t boot_crc = 0;
bool flash_ok;

static inline u_int32_t crc32_for(void *data, u_int32_t len)
{
    u_int32_t crc = 0;
    u_int8_t *d = (u_int8_t *)data;
    for(; len > 0; len--)
        crc = crc32_update(crc,*d++);
    if(crc == 0 || crc == ~0U)
        crc ^= 1;
    return crc;
}

bool flash_check(struct flash_hdr *flash)
{
    if (flash->magic != FLASH_MAGIC) { // flashctx
        logger("Bad magic x%x x%x", flash->magic, FLASH_MAGIC);
        return false;
    }
    if (((u_int32_t)flash->ram_start<<2)+BootRAMstart != (u_int32_t)&AppRAMstart) {
        logger("Bad RAM start x%x x%x", (u_int32_t)flash->ram_start<<2, &AppRAMstart);
        return false;
    }
    if(flash->boot_crc && boot_crc != flash->boot_crc) {
        logger("Boot CRC x%x x%x", flash->boot_crc, boot_crc);
        return false;
    }
    u_int32_t crc = crc32_for(flash->data, flash->app_len*FLASH_BLOCK);
    if (crc != flash->app_crc) {
        logger("Bad AppCRC x%x x%x", flash->app_crc, crc);
        return false;
    }
    return true;
}

char process_control_flash(BusMessage msg, u_int8_t *data, msglen_t len)
{
    const char *estr = NULL;
    if (msg->dst != my_addr)
        return 0;
    if (msg->src == -4 || msg->src >= 0) {
        logger("Flash from %d",msg->src);
        return 0;
    }

    BusMessage m = msg_alloc(8);
    msg_start_send(m);
    m->code = 0;
    m->dst = msg->src;
    m->src = my_addr;

    len--;
    bool flg = (*data & 0x10) != 0;
    u_int8_t typ = *data++ & 0x0F;
    if(flg)
        goto err;

    if(flash_start_mtimer) {
        estr = logger("timer waiting");
        goto err;
    }
    switch (typ) {
    case 0: // checksum app
        if(!flash_check(&AppHdr))
            goto err;
        msg_add_byte(m, (1<<5)|typ);
        msg_add_32(m, AppHdr.app_crc);
        msg_add_16(m, AppHdr.app_version);
        send_msg(m);
        msg = NULL;
        break;
    case 1: // bootloader version
        msg_add_byte(m, (1<<5)|typ);
        msg_add_32(m, FLASH_MAGIC);
        msg_add_32(m, boot_crc);
        send_msg(m);
        msg = NULL;
        break;
    case 4: //  clear
        if(len < 6)
            goto err;
        // 2 byte boot version, 2 byte start offset, 2 byte len)
        {
            // existing bootloader CRC
            u_int32_t nr = get_32(data);
            if(nr != boot_crc) {
                estr = logger("Boot x%x??", nr);
                goto err;
            }
        }
        // FALL THRU
    case 5: //  clear boot
        {

            // start block. Zero for "doesn't matter", i.e. position-independent code
            u_int16_t nr = get_16(data);
            u_int16_t sb = (((u_int32_t)&AppHdr - (u_int32_t)&BootFLASHstart)/FLASH_BLOCK);
            if(nr != 0 && nr != sb) {
                estr = logger("Addr x%x?? x%x", nr, sb);
                goto err;
            }

            // nr of blocks
            nr = get_16(data);
            if (nr == 0 || nr > AppFLASHsize/FLASH_BLOCK) {
                estr = logger("Size x%x??", nr);
                goto err;
            }

            if(flash_ok)
                (*AppHdr.stop)();
            flash_ok = false;
            
            if(!flash_erase(&AppHdr, nr*FLASH_BLOCK)) {
                estr = logger("Erase failed");
                goto err;
            }
        }
        break;

    case 6:
        if (len < 5) {
            estr = logger("short %d",len);
            goto err;
        }
        {
            len -= 4;
            u_int16_t nr = get_16(data);
            u_int16_t crc_wanted = get_16(data);
            u_int16_t crc = 0;
            crc = crc16_update(crc, msg->src & 0xFF);
            crc = crc16_update(crc, msg->dst);
            crc = crc16_update(crc, nr >> 8);
            crc = crc16_update(crc, nr & 0xFF);
            for(int n = 0;n < len; n++)
                crc = crc16_update(crc, data[n]);
            if(crc != crc_wanted) {
                estr = logger("CRC fail x%x x%x",crc_wanted,crc);
                goto err;
            }
            if(!flash_write(block2addr(nr), data, len)) {
                estr = logger("write problem %d",nr);
                goto err;
            }
        }
        break;

    case 7:
        if(len < 5)
            goto err;
        {
            u_int32_t crc = get_32(data);
            u_int8_t timer = *data++;
            if(crc != AppHdr.app_crc) {
                estr = logger("ECRC wrong");
                goto err;
            }
            if (!flash_check(&AppHdr)) {
                estr = logger("ECRC bad");
                goto err;
            }
            if(timer) {
                flash_start_mtimer = (MTICK)calloc(1, sizeof(*flash_start_mtimer));
                mtick_init(flash_start_mtimer, run_flash_start);
                mf_set(&flash_start_mtimer->mf, timer);
            } else {
                setup_flash_nocheck();
            }
        }
        break;

    default:
    err:
        logger("on %s", msg_info(msg));
        msg_add_byte(m, (1<<5)|0x10|typ);
        if(!estr)
            estr = "?";
        u_int8_t len = strlen(estr);
        msg_add_byte(m, len-1);
        msg_add_data(m, (u_int8_t *)estr,len);
        send_msg(m);
        m = NULL;
        break;
    }
        
    if(m) {
        msg_add_byte(m, (1<<5)|typ);
        send_msg(m);
    }
    return 1;
}

char process_app_msg(BusMessage msg) {
    if(!flash_ok)
        return false;
    return (*AppHdr.process)(msg);
}

static u_int16_t app_ram_size = 0;

void setup_flash() {
    flash_start_mtimer = NULL;

    boot_crc = crc32_for(&BootFLASHstart, (u_int8_t *)&BootFLASHend-&BootFLASHstart);

    flash_ok = flash_check(&AppHdr);
    if(!flash_ok)
        logger("App not OK.");
    else
        setup_flash_nocheck();
}

static void setup_flash_nocheck() {
    if(!app_ram_size) {
        u_int8_t *brk = (u_int8_t *)sbrk(0);
        if (&AppRAMend != brk) {
            logger("RAM end x%x x%x", AppRAMend, brk);
            flash_ok = false;
            return;
        }
        u_int32_t mem = &AppRAMend-&AppRAMstart;
        if (mem < ((u_int32_t)AppHdr.ram_len<<2)) {
            brk = (u_int8_t *)sbrk(((u_int32_t)AppHdr.ram_len<<2) - mem);
            app_ram_size = brk-&AppRAMstart;
        } else {
            app_ram_size = &AppRAMend - &AppRAMstart;
        }
    } else {
        if ((AppHdr.ram_len<<2) > app_ram_size) {
            logger("RAM want x%x x%x", (AppHdr.ram_len<<2), app_ram_size);
            flash_ok = false;
            return;
        }
    }

    if(!(*AppHdr.start)()) {
        logger("App did not initialize.");
    } else {
        flash_ok = true;
        logger("App OK.");
    }
}

void loop_flash() {
    if(flash_ok)
        (*AppHdr.loop)();
}

