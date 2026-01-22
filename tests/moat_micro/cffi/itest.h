// Test interface

struct itest;

struct itest_cb {
    void *user;
    int (*callback)(void *user, int param);
};

struct itest *itest_setup(struct itest_cb *cb, int param);
void itest_free(struct itest *);

int itest_call(struct itest *, int param);
