/* SPDX-License-Identifier: MIT */
#ifndef CK_MINI_STDLIB_H
#define CK_MINI_STDLIB_H
#include <stddef.h>
/* Declaration only; dynamic allocation is disabled in this example. */
void *malloc(size_t);
void free(void *);
#endif
