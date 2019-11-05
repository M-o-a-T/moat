import math

def mini2byte(f):
    if f <= 32:
        return f
    exp = 1
    while f >= 32: # not an error because of normalization
        f >>= 1
        exp += 1
    return (exp<<4) | (f&0xf)

def byte2mini(m):
    if m <= 32:
        return m
    #import pdb;pdb.set_trace()
    exp = (m>>4)-1
    m = 16+(m&0xf)
    return 2**exp*m


if __name__ == "__main__":
    for x in range(256):
        print(x,byte2mini(x)/4,mini2byte(byte2mini(x)))

    
