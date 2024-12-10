"""
Steinhart-Hart NTC thermistor formulae
"""

from math import log, exp

NOMINAL_TEMPERATURE=25
ADC_BITS = 10

__ALL__ = [ "thermistor2celsius", "celsius2thermistor"]


def thermistor2celsius(B:int, raw:int, bits:int = ADC_BITS) -> float:
	# source: https://arduinodiy.wordpress.com/2015/11/10/measuring-temperature-with-ntc-the-steinhart-hart-formula/
	if raw == 0:
		return None

	res = ((1<<bits)-1) / raw - 1.0
	res = log(res)/B + 1 / (NOMINAL_TEMPERATURE + 273.15)
	res = 1.0 / res - 273.15

	return res


def celsius2thermistor(B: int, degC:float, bits:int = ADC_BITS) -> int:
	if degC is None:
		return 0
	res = 1 / (degC + 273.15) - 1 / (NOMINAL_TEMPERATURE + 273.15)
	res = exp(res * B)
	res = ((1<<bits)-1) / (res+1.0)

	return int(res+0.5)

