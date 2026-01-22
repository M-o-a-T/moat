#!/bin/sh

gcc -g -O0 --shared -o itest.so itest.c
gcc -g -O0 -o test test.c -ldl
./test
