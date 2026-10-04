OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 16M }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
  .text : { KEEP(*(.text.start)) *(.text*) } > RAM :text
  .rodata : { *(.rodata*) } > RAM :text
  .crashkit_id : { KEEP(*(.crashkit_id)) } > RAM :text
  .data : { __global_pointer$ = . + 0x800; *(.sdata*) *(.data*) } > RAM :data
  .bss (NOLOAD) : {
    . = ALIGN(16); __bss_start = .; *(.sbss*) *(.bss*) *(COMMON)
    . = ALIGN(16); __bss_end = .;
  } > RAM :data
  . = ALIGN(16); . += 8192; __stack_top = .;
  __freertos_irq_stack_top = __stack_top;
  __ram_end = ORIGIN(RAM) + LENGTH(RAM);
  ASSERT(__stack_top < __ram_end, "RAM overflow")
}
