/* SPDX-License-Identifier: MIT */
/* Host-only synthetic example. File I/O below is NOT a fatal-path backend. */
#include "crashkit.h"
#include <stdio.h>

int main(int argc, char **argv)
{
    uint8_t buffer[256];
    struct ck_writer writer;
    struct ck_identity identity = {
        .architecture = CK_ARCH_GENERIC, .pointer_bits = 32,
        .source_endian = 1, .reason = CK_REASON_MANUAL,
        .flags = CK_FLAG_SYNTHETIC, .sequence = 1
    };
    const uint64_t registers[] = { 0x12345678, 0x80001000 };
    size_t written = 0;
    FILE *output;
    if (argc != 2) {
        fprintf(stderr, "Usage: %s output.bin\n", argv[0]);
        return 2;
    }
    if (ck_begin(&writer, buffer, sizeof(buffer), &identity) != CK_OK ||
        ck_registers(&writer, registers, 2, 32, 3) != CK_OK ||
        ck_diagnostic(&writer, 100, 42) != CK_OK ||
        ck_finish(&writer, &written) != CK_OK)
        return 1;
    output = fopen(argv[1], "wb");
    if (!output) return 1;
    if (fwrite(buffer, 1, written, output) != written) {
        fclose(output);
        return 1;
    }
    return fclose(output) != 0;
}
