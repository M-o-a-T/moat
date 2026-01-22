#!/bin/sh

gcc -O2 --shared -o itest.so itest.c
gcc -O2 -o test test.c -ldl
./test
