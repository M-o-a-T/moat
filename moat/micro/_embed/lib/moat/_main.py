import uasyncio

async def main(setup):
    evt = uasyncio.Event()
    await setup(evt)

    while True:
        print("running")
        try:
            await uasyncio.wait_for(evt.wait(), 10)
        except uasyncio.TimeoutError:
            continue
        else:
            break

def moat_run(setup):
    uasyncio.run(main(setup))

