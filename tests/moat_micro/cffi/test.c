#include "itest.h"

#include <stdio.h>

int times(void *it, int param)
{
    return param * (*(int *)(it));
}

int main() {
    int here = 2;

    struct itest *tst;
    struct itest_cb cb = {&here, times};
    tst = itest_setup(&cb, 5);
    printf("%d\n", itest_call(tst, 3));
    itest_free(tst);

    return 0;
}
