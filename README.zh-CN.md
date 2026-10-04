# FreeRTOS CrashKit

An independent, portable crash-capture component with an offline evidence reader.
Original component code; official FreeRTOS is a separately pinned dependency.

独立设计的FreeRTOS故障采集组件：固定内存、明确缺失、CPU/OS/板级边界分离。第一版目标是单核通用RV32，验证平台为QEMU virt，不绑定芯片厂商，不依赖厂商故障分析工具。实验性0.1.0候选源码已推送到 [公开仓库](https://github.com/YvainZhang/freertos-crashkit)，GCC/Clang与RV32远程CI已通过；正式tag和Release尚未创建。英文入口见 [README](README.md)，发布流程见 [RELEASING](docs/RELEASING.md)。

## 已实现

- 无动态分配/日志锁/调度器调用的C采集核心；版本化二进制格式、记录CRC和完成标记。
- 有界任务元数据登记；FreeRTOS适配使用公开API和显式静态任务登记，不修改内核。
- RV32 M-mode异常向量、独立故障栈、通用寄存器与CSR保存、嵌套故障中止。
- Python离线解析、固件身份匹配、JSON/HTML报告。只读解析，不在故障镜像里执行目标函数。
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
python3 tools/analyze.py evidence/qemu-rv32/1.bin --elf build/rv32/1/firmware.elf --json build/report.json --html build/report.html
```

下载工具校验锁定的官方归档；已有归档可用`--archive <path>`复用。构建不修改已有项目、容器或FreeRTOS源码。工具容器以当前用户UID/GID运行，移除capabilities后仍能写入自己拥有的挂载目录，避免Linux runner的root无权限问题。已有生成文件也需由该用户可写。工具容器只挂载本项目，无网络；不要在共享生产环境注入故障。

## 文档与边界

按 [接入与API契约](docs/PORTING.md)接入，快照格式见 [FORMAT](docs/FORMAT.md)，源码包与版本发布流程见 [RELEASING](docs/RELEASING.md)。这些公开文档说明支持范围、集成要求与验证方法。

当前任务记录是登记时的名称/优先级/栈区域，不声称故障时的Ready/Blocked状态或完整任务枚举。尚无完整多任务回溯、死锁定因、SMP、RV64、F/V寄存器、物理掉电持久化或真实芯片验收。QEMU输出是测试载体；板端保存接口需根据存储/看门狗/异常上下文实现。CRC用于损坏检测，不用于认证。0.x源码API允许在次版本调整，无二进制ABI承诺；快照格式独立版本化。英文API契约与兼容矩阵见 [PORTING](docs/PORTING.md)。

## Source layout

`include/` public API; `src/` portable encoder/registry; `ports/freertos/` normal-context integration; `ports/rv32/` CPU entry; `examples/qemu-rv32/` reference BSP; `tools/` offline reader; `tests/` corruption tests; `evidence/` recorded results. `third_party/` is generated, pinned upstream code; `build/` contains generated ELF and logs.

## License

Original code: [MIT](LICENSE). FreeRTOS: upstream MIT, see the downloaded kernel's LICENSE.md and [第三方依赖说明](THIRD_PARTY_NOTICES.md). No proprietary firmware, customer dumps or vendor tool implementation is distributed.
