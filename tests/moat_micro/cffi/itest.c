#include "itest.h"

#include <memory.h>
#include <stdlib.h>

struct itest {
    struct itest_cb *cb;
    int param;
};

struct itest *itest_setup(struct itest_cb *cb, int param)
{
    struct itest *tst = malloc(sizeof(struct itest));
    memset(tst,0,sizeof(*tst));
    tst->cb = cb;
    tst->param = 7;
    return tst;
}

void itest_free(struct itest *tst)
{
    free(tst);
}

int itest_call(struct itest *tst, int param)
{
    return param * tst->param * tst->cb->callback(tst->cb->user, param);
}
