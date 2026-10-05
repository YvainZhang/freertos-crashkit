# FreeRTOS CrashKit

An independent, portable crash-capture and post-mortem debugging toolkit.
Original component code; official FreeRTOS is a separately pinned dependency.

独立设计的FreeRTOS故障采集与死后调试工具：固定预算、明确缺失、CPU/OS/板级边界分离。当前为实验性0.2.0候选，使用单核通用RV32和QEMU virt，不绑定芯片厂商。源码入口为 [公开仓库](https://github.com/YvainZhang/freertos-crashkit)，请在 [GitHub Actions](https://github.com/YvainZhang/freertos-crashkit/actions) 核对所用提交的CI结果；源码公开不等于已创建正式tag/Release。英文入口见 [README](README.md)，交互调试见 [DEBUGGING](docs/DEBUGGING.md)。

## 已实现

- 无动态分配/日志锁/调度器调用的C采集核心；版本化二进制格式、记录CRC和完成标记。
- 有界任务元数据登记；FreeRTOS适配使用公开API和显式静态任务登记，不修改内核。
- RV32 M-mode异常向量、独立故障栈、通用寄存器与CSR保存、嵌套故障中止。
- Python离线解析、固件身份匹配、JSON/HTML报告。只读解析，不在故障镜像里执行目标函数。
- 离线任务重建、保存上下文恢复、栈剩余量和帧链；GDB支持任务切换、DWARF回溯、局部/全局变量。
- 队列及等待者、信号量/互斥锁、事件组、流缓冲区、软件定时器、heap_4与有界事件历史。
- 可选分析副本：写寄存器/内存、RV32虚拟执行ELF辅助函数、重置；原始快照保持不变。
- 主机故障/容量/格式测试、ASan/UBSan；官方FreeRTOS V11.1.0在QEMU中运行并注入真实异常。

## 快速开始

主机需要C11编译器、Python≥3.9（使用3.9及以上的路径API；QEMU测试脚本含assignment expression）。交叉构建使用Docker，验证使用qemu-system-riscv32。

```sh
make test
make sanitize
make verify  # 同时构建主机静态库、合成演示并检查文档链接
python3 scripts/fetch-freertos.py
docker build -f scripts/Dockerfile.rv32 -t freertos-crashkit-rv32:bookworm .
docker run --rm --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 512m -v "$PWD:/work" -w /work freertos-crashkit-rv32:bookworm python3 scripts/build-rv32.py
make qemu-test
python3 tools/analyze.py evidence/qemu-rv32/1.bin --elf build/rv32/1/firmware.elf --debug --json build/report.json --html build/report.html
docker run --rm --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 512m -v "$PWD:/work" -w /work freertos-crashkit-rv32:bookworm python3 scripts/test-debug.py
```

下载工具校验锁定的官方归档；已有归档可用`--archive <path>`复用。构建不修改已有项目、容器或FreeRTOS源码。工具容器以当前用户UID/GID运行，移除capabilities后仍能写入自己拥有的挂载目录，避免Linux runner的root无权限问题。已有生成文件也需由该用户可写。工具容器只挂载本项目，无网络；不要在共享生产环境注入故障。

## 文档与边界

按 [接入与API契约](docs/PORTING.md)接入，快照格式见 [FORMAT](docs/FORMAT.md)，源码包与版本发布流程见 [RELEASING](docs/RELEASING.md)。这些公开文档说明支持范围、集成要求与验证方法。

Type-3任务记录仍是登记元数据；新增离线视图根据匹配ELF及冻结内核RAM重建故障时状态，损坏或缺失时明确降级。当前自动视图限FreeRTOS V11.1.0与参考RV32上下文，不支持SMP、RV64或F/V。Python回溯要求帧指针；GDB结合DWARF分析，优化掉的信息无法恢复。尚无自动死锁定因、真实芯片验收或掉电持久化。芯片寄存器使用缓存采样与用户提供的字段/时钟树配置，QEMU示例不代表厂商适配已验证。默认GDB只读，开启执行后仅修改分析副本；不得在真设备调用虚拟地址辅助函数。

CPU异常（含真实定时器ISR）、assert和真实内核栈哨兵检测分别验收；中断异常视图与被中断任务的保存上下文分开。栈哨兵破坏测试不等于已覆盖所有SP失效情形。CRC用于损坏检测，不用于认证。0.x源码API允许次版本调整，格式v1保持原字段编码，0.2.0扩大了输入长度上限。接入与预算见 [PORTING](docs/PORTING.md)。

## Source layout

`include/` public API; `src/` portable encoder/registry; `ports/freertos/` normal-context integration; `ports/rv32/` CPU entry; `examples/qemu-rv32/` reference BSP; `tools/` offline reader; `tests/` corruption tests; `evidence/` recorded results. `third_party/` is generated, pinned upstream code; `build/` contains generated ELF and logs.

## License

Original code: [MIT](LICENSE). FreeRTOS: upstream MIT, see the downloaded kernel's LICENSE.md and [第三方依赖说明](THIRD_PARTY_NOTICES.md). No proprietary firmware, customer dumps or vendor tool implementation is distributed.
