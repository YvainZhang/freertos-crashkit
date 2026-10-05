OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
  RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 16M
  DEBUG (rx) : ORIGIN = 0xf0000000, LENGTH = 256K
}
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); analysis PT_NULL FLAGS(5); }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) } > RAM :text
  .rodata : { *(.rodata*) } > RAM :text
  .crashkit_id : { KEEP(*(.crashkit_id)) } > RAM :text
  .crashkit_layout : { KEEP(*(.crashkit_layout)) } > RAM :text
  .crashkit_objects : { KEEP(*(.crashkit_objects)) } > RAM :text
  .data : { __capture_start = .; __global_pointer$ = . + 0x800; *(.sdata*) *(.data*) } > RAM :data
  .bss (NOLOAD) : {
    . = ALIGN(16); __bss_start = .; *(.sbss*) *(.bss*) *(COMMON)
    . = ALIGN(16); __bss_end = .; __capture_end = .;
  } > RAM :data
  .crashkit_workspace (NOLOAD) : { *(.crashkit_workspace) } > RAM :data
  .crashkit_dump (NOLOAD) : { *(.crashkit_dump) } > RAM :data
  . = ALIGN(16); __irq_stack_bottom = .; . += 8192; __stack_top = .;
  __freertos_irq_stack_top = __stack_top;
  __ram_end = ORIGIN(RAM) + LENGTH(RAM);
  ASSERT(__stack_top < __ram_end, "RAM overflow")
  /* ELF-only code: PROGBITS retained, no PT_LOAD and no device image bytes. */
  .crashkit_debug : { KEEP(*(.crashkit_debug)) } > DEBUG :analysis
  .crashkit_debug_rodata : { KEEP(*(.crashkit_debug_rodata)) } > DEBUG :analysis
}
