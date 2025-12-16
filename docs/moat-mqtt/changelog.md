# Changelog

## 0.10

- Ported to anyio, thus works with asyncio+trio+curio.
- Refactored so that closed connections don't affect message delivery.

## 0.9.5

- fix [more
  issues](https://github.com/beerfactory/distmqtt/milestone/11?closed=1)
- fix a [few
  issues](https://github.com/beerfactory/distmqtt/milestone/10?closed=1)

## 0.9.2

- fix a [few
  issues](https://github.com/beerfactory/distmqtt/milestone/9?closed=1)

## 0.9.1

- See commit log

## 0.9.0

- fix a [serie of
  issues](https://github.com/beerfactory/distmqtt/milestone/8?closed=1)
- improve plugin performance
- support Python 3.6
- upgrade to `websockets` 3.3.0

## 0.8.0

- fix a [serie of
  issues](https://github.com/beerfactory/distmqtt/milestone/7?closed=1)

## 0.7.3

- fix deliver message client method to raise TimeoutError
  ([\#40](https://github.com/beerfactory/distmqtt/issues/40))
- fix topic filter matching in broker
  ([\#41](https://github.com/beerfactory/distmqtt/issues/41))

Version 0.7.2 has been jumped due to troubles with pypi...

## 0.7.1

- Fix [duplicated \$SYS topic
  name](https://github.com/beerfactory/distmqtt/issues/37) .

## 0.7.0

- Fix a [serie of
  issues](https://github.com/beerfactory/distmqtt/issues?q=milestone%3A0.7+is%3Aclosed)
  reported by [Christoph Krey](https://github.com/ckrey)

## 0.6.3

- Fix issue [\#22](https://github.com/beerfactory/distmqtt/issues/22).

## 0.6.2

- Fix issue [\#20](https://github.com/beerfactory/distmqtt/issues/20)
  (`mqtt` subprotocol was missing).
- Upgrade to `websockets` 3.0.

## 0.6.1

- Fix issue [\#19](https://github.com/beerfactory/distmqtt/issues/19)

## 0.6

- Added compatibility with Python 3.5.
- Rewritten documentation.
- Add command-line tools `references/distmqtt`,
  `references/distmqtt_pub` and `references/distmqtt_sub`.
