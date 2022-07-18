#!/usr/bin/python3
import os
from elftools.elf.elffile import ELFFile
from elftools.elf.constants import SH_FLAGS
from moatbus.crc import CRC32

Import("env")
try:
    Import("projenv")
except Exception:
    projenv = None

def skip_fake(node):
    # to ignore file from a build process, just return None
    if node.get_dir().name in {"fakebus","tests"}:
        return None
    mode = env.GetProjectOption("mode")

    n = node
    while n.get_dir().name != "src" and n.get_dir().get_dir().name != ".pio":
        n = n.get_dir()
    if n.name in {"picolibc"}:
        return None

    if mode == "app":
        if node.get_dir().name in {"app"}:
            return node
        return None
    else:
        if node.get_dir().name in {"app"}:
            return None
        return node

def run_pre():
    env.AddBuildMiddleware(skip_fake, "*")
    mode = env.GetProjectOption("mode")
    if mode == "app":
        base = env.GetProjectOption("base")
        # We need to insert the gate addresses after the actual objects
        # so that we won't override them.
        env.Replace(LINKCOM=[env['LINKCOM'].replace(' $_LIBDIRFLAGS ', ' $LDAUXFLAGS $_LIBDIRFLAGS ')])
        f = os.path.join(".pio","build",base,"firmware.elf")
        env.Replace(LDAUXFLAGS=["-Wl,-R,"+ f])

        ff = os.path.join(".pio","build",env['PIOENV'],"firmware.elf")
        env.Depends(ff,f)
        ff = os.path.join(".pio","build",env['PIOENV'],"src","app","base.cpp.o")
        env.Depends(ff,f)
        with open(f,"rb") as stream:
            elffile = ELFFile(stream)

            s = None
            crc = CRC32()
            sl = []

            for section in elffile.iter_sections():
                if section.is_null():
                    continue
                if not (section.header.sh_flags & SH_FLAGS.SHF_ALLOC):
                    continue
                if section['sh_type'] == 'SHT_NOBITS':
                    continue
                for seg in elffile.iter_segments():
                    if seg.section_in_segment(section):
                        section.header.sh_addr += seg['p_paddr']-seg['p_vaddr']
                        break
                print("%s:x%x" % (section.header.sh_name,section.header.sh_offset))
                sl.append(section)

            for section in sorted(sl, key=lambda s:s.header.sh_addr):
                off = section.header.sh_addr
                if s is not None and s != off:
                    raise RuntimeError("Wrong offset: x%x vs x%x" % (s,off))
                s = off + section.header.sh_size

                for d in section.data():
                    crc.update(d)

            section = elffile.get_section_by_name('.symtab')
            ram_end = section.get_symbol_by_name("AppRAMstart")[0].entry.st_value
            ram_start = section.get_symbol_by_name("_sdata")[0].entry.st_value
            flash_start = section.get_symbol_by_name("AppFLASHstart")[0].entry.st_value
            env.Append(LINKFLAGS=[
            "-Wl,--defsym=APP_DATA_START=0x%x"%ram_end,
            "-Wl,--defsym=APP_FLASH_START=0x%x"%flash_start,
                ])
            env.Append(CPPFLAGS=["-D BOOT_CRC=0x%x"%crc.finish()])


def run_post():
    pass


if projenv:
    run_post()
else:
    run_pre()
