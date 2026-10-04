/* SPDX-License-Identifier: MIT */
#ifndef CK_MINI_STRING_H
#define CK_MINI_STRING_H
#include <stddef.h>
void *memcpy(void *, const void *, size_t);
void *memset(void *, int, size_t);
int memcmp(const void *, const void *, size_t);
size_t strlen(const char *);
#endif
