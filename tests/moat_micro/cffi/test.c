#include "itest.h"

#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

// Function pointer types for dynamically loaded functions
typedef struct itest* (*itest_setup_t)(struct itest_cb *cb, int param);
typedef void (*itest_free_t)(struct itest *);
typedef int (*itest_call_t)(struct itest *, int param);

int times(void *it, int param)
{
    return param * (*(int *)(it));
}

int main() {
    int here = 2;
    void *handle;
    itest_setup_t itest_setup;
    itest_free_t itest_free;
    itest_call_t itest_call;
    char *error;

    // Load the shared library
    handle = dlopen("./itest.so", RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Error loading itest.so: %s\n", dlerror());
        return 1;
    }

    // Clear any existing error
    dlerror();

    // Load the symbols
    *(void **)(&itest_setup) = dlsym(handle, "itest_setup");
    if ((error = dlerror()) != NULL) {
        fprintf(stderr, "Error loading itest_setup: %s\n", error);
        dlclose(handle);
        return 1;
    }

    *(void **)(&itest_free) = dlsym(handle, "itest_free");
    if ((error = dlerror()) != NULL) {
        fprintf(stderr, "Error loading itest_free: %s\n", error);
        dlclose(handle);
        return 1;
    }

    *(void **)(&itest_call) = dlsym(handle, "itest_call");
    if ((error = dlerror()) != NULL) {
        fprintf(stderr, "Error loading itest_call: %s\n", error);
        dlclose(handle);
        return 1;
    }

    // Run the test
    struct itest *tst;
    struct itest_cb cb = {&here, times};
    tst = itest_setup(&cb, 5);
    printf("%d\n", itest_call(tst, 3));
    itest_free(tst);

    // Close the library
    dlclose(handle);

    return 0;
}
