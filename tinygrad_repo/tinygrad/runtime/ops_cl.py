from __future__ import annotations
from typing import cast
import ctypes, functools, hashlib, os
from tinygrad.runtime.autogen import opencl as cl
from tinygrad.helpers import init_c_var, to_char_p_p, from_mv, OSX, DEBUG, mv_address, suppress_finalizing, getenv
from tinygrad.renderer.cstyle import OpenCLRenderer, IntelRenderer, CStyleLanguage, create_non_native_float_pats, extra_pm
from tinygrad.device import BufferSpec, LRUAllocator, Compiled, Compiler, CompileError
from tinygrad.dtype import dtypes

# see test/external/external_osx_profiling.py to determine this ratio. it's in like GPU clocks or something
OSX_TIMING_RATIO = (125/3) if OSX else 1.0

cl_errors = {attr: k for k in dir(cl) if k.startswith("CL_") and isinstance(attr:=getattr(cl, k), int) and attr <= 0}
def check(status):
  if status != 0: raise RuntimeError(f"OpenCL Error {status}: {cl_errors.get(status, 'Unknown error')}")
def checked(ret, status): return (check(status.value), ret)[1]

class CLCompiler(Compiler):
  def __init__(self, dev:CLDevice, compile_key:str):
    self.dev = dev
    super().__init__(f"compile_cl_{compile_key}")
  def compile(self, src:str) -> bytes:
    program = checked(cl.clCreateProgramWithSource(self.dev.context, 1, to_char_p_p([src.encode()]), None, status := ctypes.c_int32()), status)

    # 简化的编译选项控制：只在用户明确设置时使用
    build_options = None
    optimization_level = getenv("CL_OPTIMIZATION_LEVEL", "")

    if optimization_level == "0":
      # 禁用优化（用户明确设置）
      build_options = None  # 不使用任何优化选项
    elif optimization_level == "2":
      # 激进优化（用户明确设置）
      build_options = "-cl-mad-enable -cl-fast-relaxed-math -cl-unsafe-math-optimizations".encode()
    # 默认情况（包括optimization_level=1或未设置）使用原始行为（None）

    # 简化的架构支持：只在TARGET_ARCH明确设置时使用
    target_arch = os.environ.get("TARGET_ARCH")
    if target_arch and build_options:
      # 只在有编译选项的情况下添加架构选项
      build_options += f" -arch {target_arch}".encode()

    build_status: int = cl.clBuildProgram(program, 1, self.dev.device_id, build_options, cl.clBuildProgram.argtypes[4](), None)
    if build_status != 0:
      cl.clGetProgramBuildInfo(program, self.dev.device_id, cl.CL_PROGRAM_BUILD_LOG, 0, None, log_size := ctypes.c_size_t())
      cl.clGetProgramBuildInfo(program, self.dev.device_id, cl.CL_PROGRAM_BUILD_LOG,
                               log_size.value, mstr := ctypes.create_string_buffer(log_size.value), None)
      raise CompileError(f"OpenCL Compile Error\n\n{mstr.value.decode()}")
    check(cl.clGetProgramInfo(program, cl.CL_PROGRAM_BINARY_SIZES, ctypes.sizeof(ctypes.c_size_t), binary_sizes := (ctypes.c_size_t * 1)(), None))
    check(cl.clGetProgramInfo(program, cl.CL_PROGRAM_BINARIES, ctypes.sizeof(ctypes.c_void_p),
                              (ctypes.c_void_p * 1)(ctypes.addressof(binary := ctypes.create_string_buffer(binary_sizes[0]))), None))
    check(cl.clReleaseProgram(program))
    return bytes(binary)

class CLProgram:
  def __init__(self, device:CLDevice, name:str, lib:bytes):
    self.dev, self.name, self.lib = device, name, lib
    self.program = checked(cl.clCreateProgramWithBinary(device.context, 1, device.device_id, (ctypes.c_size_t * 1)(len(lib)),
                                                        to_char_p_p([lib], ctypes.c_ubyte), binary_status := ctypes.c_int32(),
                                                        errcode_ret := ctypes.c_int32()), errcode_ret)
    check(binary_status.value)
    # 添加构建日志打印
    build_status = cl.clBuildProgram(self.program, 1, device.device_id, None, cl.clBuildProgram.argtypes[4](), None)
    if build_status != 0:
      cl.clGetProgramBuildInfo(self.program, device.device_id, cl.CL_PROGRAM_BUILD_LOG, 0, None, log_size := ctypes.c_size_t())
      cl.clGetProgramBuildInfo(self.program, device.device_id, cl.CL_PROGRAM_BUILD_LOG,
                               log_size.value, mstr := ctypes.create_string_buffer(log_size.value), None)
      raise RuntimeError(f"OpenCL Build Error {build_status}: {mstr.value.decode()}")
    self.kernel = checked(cl.clCreateKernel(self.program, name.encode(), status := ctypes.c_int32()), status)

  def __del__(self):
    try: check(cl.clReleaseKernel(self.kernel))
    except (TypeError, AttributeError): pass
    try: check(cl.clReleaseProgram(self.program))
    except (TypeError, AttributeError): pass

  def __call__(self, *bufs:tuple[ctypes._CData, BufferSpec], global_size:tuple[int,int,int]=(1,1,1), local_size:tuple[int,int,int]|None=None,
               vals:tuple[int, ...]=(), wait=False) -> float|None:
    for i,(b,_) in enumerate(bufs): check(cl.clSetKernelArg(self.kernel, i, ctypes.sizeof(b), ctypes.byref(b)))
    for i,v in enumerate(vals,start=len(bufs)): check(cl.clSetKernelArg(self.kernel, i, 4, ctypes.byref(ctypes.c_int32(v))))
    if local_size is not None: global_size = cast(tuple[int,int,int], tuple(int(g*l) for g,l in zip(global_size, local_size)))
    event = cl.cl_event() if wait else None
    check(cl.clEnqueueNDRangeKernel(self.dev.queue, self.kernel, len(global_size), None, (ctypes.c_size_t * len(global_size))(*global_size),
                                    (ctypes.c_size_t * len(local_size))(*local_size) if local_size else None, 0, None, event))
    if wait:
      assert event is not None
      check(cl.clWaitForEvents(1, event))
      check(cl.clGetEventProfilingInfo(event, cl.CL_PROFILING_COMMAND_START, 8, ctypes.byref(start := ctypes.c_uint64()), None))
      check(cl.clGetEventProfilingInfo(event, cl.CL_PROFILING_COMMAND_END, 8, ctypes.byref(end := ctypes.c_uint64()), None))
      return float(end.value-start.value) * OSX_TIMING_RATIO * 1e-9
    return None

class CLAllocator(LRUAllocator['CLDevice']):
  def _alloc(self, size:int, options:BufferSpec) -> tuple[ctypes._CData, BufferSpec]:
    if options.image is not None:
      return (checked(cl.clCreateImage2D(self.dev.context, cl.CL_MEM_READ_WRITE,
                                        cl.cl_image_format(cl.CL_RGBA, {2: cl.CL_HALF_FLOAT, 4: cl.CL_FLOAT}[options.image.itemsize]),
                                        options.image.shape[1], options.image.shape[0], 0, None, status := ctypes.c_int32()), status), options)
    return (checked(cl.clCreateBuffer(self.dev.context, cl.CL_MEM_READ_WRITE, size, None, status := ctypes.c_int32()), status), options)
  @suppress_finalizing
  def _free(self, opaque:tuple[ctypes._CData, BufferSpec], options:BufferSpec): check(cl.clReleaseMemObject(opaque[0]))
  def _copyin(self, dest:tuple[ctypes._CData, BufferSpec], src:memoryview):
    if dest[1].image is not None:
      check(cl.clEnqueueWriteImage(self.dev.queue, dest[0], False, (ctypes.c_size_t * 3)(0,0,0),
                                   (ctypes.c_size_t * 3)(dest[1].image.shape[1],dest[1].image.shape[0],1), 0, 0, from_mv(src), 0, None, None))
    else:
      if mv_address(src) % 16: src = memoryview(bytearray(src))
      check(cl.clEnqueueWriteBuffer(self.dev.queue, dest[0], False, 0, len(src)*src.itemsize, from_mv(src), 0, None, None))
    self.dev.pending_copyin.append(src)    # NOTE: these can't be freed until the GPU actually executes this command
  def _copyout(self, dest:memoryview, src:tuple[ctypes._CData, BufferSpec]):
    if src[1].image is not None:
      check(cl.clEnqueueReadImage(self.dev.queue, src[0], False, (ctypes.c_size_t * 3)(0,0,0),
                                  (ctypes.c_size_t * 3)(src[1].image.shape[1],src[1].image.shape[0],1), 0, 0, from_mv(dest), 0, None, None))
    else:
      check(cl.clEnqueueReadBuffer(self.dev.queue, src[0], False, 0, len(dest)*dest.itemsize, from_mv(dest), 0, None, None))
    self.dev.synchronize()

class CLDevice(Compiled):
  device_ids = None                 # this is global and only initted once
  def __init__(self, device:str=""):
    if CLDevice.device_ids is None:
      check(cl.clGetPlatformIDs(0, None, num_platforms := ctypes.c_uint32()))
      check(cl.clGetPlatformIDs(num_platforms.value, platform_ids := (cl.cl_platform_id * num_platforms.value)(), None))
      for device_type in [cl.CL_DEVICE_TYPE_GPU, cl.CL_DEVICE_TYPE_DEFAULT]:
        err = cl.clGetDeviceIDs(platform_ids[0], device_type, 0, None, num_devices := ctypes.c_uint32())
        if err == 0 and num_devices.value != 0: break
      if DEBUG >= 1: print(f"CLDevice: got {num_platforms.value} platforms and {num_devices.value} devices")
      CLDevice.device_ids = init_c_var((cl.cl_device_id * num_devices.value)(),
                                       lambda x: check(cl.clGetDeviceIDs(platform_ids[0], device_type, num_devices, x, None)))

    self.device_id = CLDevice.device_ids[0 if ":" not in device else int(device.split(":")[1])]
    self.device_name = (cl.clGetDeviceInfo(self.device_id, cl.CL_DEVICE_NAME, 256,
                                           buf:=ctypes.create_string_buffer(256), None), buf.value.decode())[1]
    self.driver_version = (cl.clGetDeviceInfo(self.device_id, cl.CL_DRIVER_VERSION, 256,
                                              buf:=ctypes.create_string_buffer(256), None), buf.value.decode())[1]
    self.context = checked(cl.clCreateContext(None, 1, self.device_id, cl.clCreateContext.argtypes[3](), None, status := ctypes.c_int32()), status)
    self.queue = checked(cl.clCreateCommandQueue(self.context, self.device_id, cl.CL_QUEUE_PROFILING_ENABLE, status), status)
    self.pending_copyin: list[memoryview] = []
    self.device_exts = (cl.clGetDeviceInfo(self.device_id, cl.CL_DEVICE_EXTENSIONS, 4096,
                                           ctypes.byref(buf := ctypes.create_string_buffer(4096)),
                                           ctypes.byref(total := ctypes.c_size_t())),
                                           ctypes.string_at(buf, size=total.value).decode())[1]

    # 获取GPU架构信息
    # 只有当用户没有显式设置时才根据设备能力自动设置
    if os.environ.get("CL_HALF") is None and "cl_khr_fp16" not in self.device_exts:
      os.environ["CL_HALF"] = "0"
    if os.environ.get("CL_INT64") is None and "cl_khr_int64" not in self.device_exts and "cl_amd_int64" not in self.device_exts:
      os.environ["CL_INT64"] = "0"

    self.device_arch = ""
    # 简化的AMD架构检测：只在用户明确启用时使用
    if getenv("CL_ARCH_DETECTION", "") == "1" and ("AMD" in self.device_name or "Radeon" in self.device_name):
      # 简化的架构检测逻辑
      if "Vega" in self.device_name:
        self.device_arch = "gfx900"
      elif "Renoir" in self.device_name or "Ryzen" in self.device_name:
        self.device_arch = "gfx90c"
      elif "Navi" in self.device_name or "RDNA" in self.device_name:
        # 简化处理：所有Navi/RDNA架构使用gfx1010
        self.device_arch = "gfx1010"
      else:
        # 默认架构
        self.device_arch = "gfx900"

    if DEBUG >= 1: print(f"CLDevice: opening {self.device_name} with version {self.driver_version}, arch {self.device_arch}")

    # 获取TARGET_ARCH环境变量并包含在缓存键中
    target_arch = os.environ.get("TARGET_ARCH", "")
    # 创建包含设备名称、驱动版本和目标架构的缓存键
    cache_key = hashlib.md5(
      self.device_name.encode() +
      self.driver_version.encode() +
      target_arch.encode()
    ).hexdigest()

    # 创建强制禁用半精度支持的自定义OpenCLRenderer子类
    class CustomOpenCLRenderer(OpenCLRenderer):
      def __init__(self, device_exts):
        self.device_exts = device_exts
        # 强制添加将half类型转换为float类型的匹配器，无论设备是否支持半精度
        self.extra_matcher = create_non_native_float_pats((dtypes.half,)) + extra_pm
        super().__init__()

      def render_kernel(self, function_name, kernel, bufs, uops, prefix=None) -> str:
        # 强制禁用半精度扩展，不添加任何半精度支持
        # 即使设备支持半精度，也强制使用单精度
        # 直接调用父类的父类（CStyleLanguage）的render_kernel方法，跳过OpenCLRenderer的扩展添加逻辑
        return CStyleLanguage.render_kernel(self, function_name, kernel, bufs, uops, prefix)

    # 创建强制禁用半精度支持的自定义IntelRenderer子类
    class CustomIntelRenderer(IntelRenderer):
      def __init__(self, device_exts):
        self.device_exts = device_exts
        # 强制添加将half类型转换为float类型的匹配器，无论设备是否支持半精度
        self.extra_matcher = create_non_native_float_pats((dtypes.half,)) + extra_pm
        super().__init__()

      def render_kernel(self, function_name, kernel, bufs, uops, prefix=None) -> str:
        # 强制禁用半精度扩展，不添加任何半精度支持
        # 即使设备支持半精度，也强制使用单精度
        # 直接调用父类的父类（CStyleLanguage）的render_kernel方法，跳过OpenCLRenderer的扩展添加逻辑
        return CStyleLanguage.render_kernel(self, function_name, kernel, bufs, uops, prefix)

    # 使用自定义渲染器
    renderer_class = CustomIntelRenderer if "cl_intel_subgroup_matrix_multiply_accumulate" in self.device_exts else CustomOpenCLRenderer
    compilers = [(functools.partial(renderer_class, self.device_exts), functools.partial(CLCompiler, self, f"compile_cl_{cache_key}"))]
    super().__init__(device, CLAllocator(self), compilers, functools.partial(CLProgram, self))
  def synchronize(self):
    check(cl.clFinish(self.queue))
    self.pending_copyin.clear()
