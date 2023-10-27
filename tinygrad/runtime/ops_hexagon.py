import time, ctypes, subprocess, platform, functools, pathlib, tempfile, contextlib, os, stat
from typing import Any
from functools import partial, reduce
from tinygrad.ops import Compiled
from tinygrad.helpers import fromimport, getenv, DEBUG, CI, cache_compiled
from tinygrad.runtime.lib import RawMallocBuffer
from tinygrad.codegen.kernel import LinearizerOptions
from tinygrad.renderer.cstyle import uops_to_cstyle, CStyleLanguage
import struct
import numpy as np

args = {'cflags':' ', 'ext':'so', 'exp':''}

CLANG_PROGRAM_HEADER = """
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define max(x,y) ((x>y)?x:y)
#define int64 long
#define half __fp16
#define uchar unsigned char
#define bool uchar

"""

CLANG_PROGRAM_FOOTER = """
//argv[0] is the elf path
//argv[1] is the output buffer
// argv[2] ... are the output buffers

float* load(char* path){{
  FILE* fp = fopen(path, "rb");
  fseek(fp, 0, SEEK_END);
  int sz = (int) ftell(fp);
  float* data = malloc(sz);
  fseek(fp, 0, SEEK_SET);
  fread(data, sz, 1, fp);
  printf("%s %d\\n",path,sz);
  return data;
}}

int main(int argc, char** argv) {{
   printf("argc %d\\n",argc);
   for(int i = 0; i < argc; i++){{printf("%s\\n",argv[i]);}}
   
   //output data
   FILE* fp = fopen(argv[1], "rb");
   fseek(fp,0,SEEK_END);
   int sz0 = (int)ftell(fp);
   fclose(fp);
   float* data0 = malloc(sz0);
   
   #if ARGC == 3
     float* data1 = load(argv[2]);
     {NAME}(data0,data1);
   #endif
   
   #if ARGC == 4
     float* data1 = load(argv[2]);
     float* data2 = load(argv[3]);
     {NAME}(data0, data1, data2);
   #endif
   
   #if ARGC == 5
     float* data1 = load(argv[2]);
     float* data2 = load(argv[3]);
     float* data3 = load(argv[4]);
     {NAME}(data0, data1, data2, data3);
   #endif
   
   #if ARGC == 6
     float* data1 = load(argv[2]);
     float* data2 = load(argv[3]);
     float* data3 = load(argv[4]);
     float* data4 = load(argv[5]);
     {NAME}(data0, data1, data2, data3, data4);
   #endif
   
   #if ARGC == 7
     float* data1 = load(argv[2]);
     float* data2 = load(argv[3]);
     float* data3 = load(argv[4]);
     float* data4 = load(argv[5]);
     float* data5 = load(argv[6]);
     {NAME}(data0, data1, data2, data3, data4, data5);
   #endif
   
   
   #if ARGC == 8
     float* data1 = load(argv[2]);
     float* data2 = load(argv[3]);
     float* data3 = load(argv[4]);
     float* data4 = load(argv[5]);
     float* data5 = load(argv[6]);
     float* data6 = load(argv[7]);
     {NAME}(data0, data1, data2, data3, data4, data5, data6);
   #endif
   
   
   fp = fopen(argv[1],"wb");
   fwrite(data0,sz0,1,fp);
   printf("all done!\\n");
   return 0;
}}
"""

HEXAGON_SDK_PATH = "/opt/Qualcomm/Hexagon_SDK/3.5.4/tools/HEXAGON_Tools/8.3.07/Tools/bin"

class HexagonProgram:
  def __init__(self, name: str, prg: str, binary: bool = False):
    print("hexagon!")
    assert not binary
    if DEBUG >= 5: print(prg)
    self.prgname = name
    self.prgstr = CLANG_PROGRAM_HEADER + prg + CLANG_PROGRAM_FOOTER.format(NAME=name)

  def compile(self, prg, binary) -> str:
    pass

  def __call__(self, global_size, local_size, *args, wait=False):
    with tempfile.NamedTemporaryFile(delete=False, suffix='.hexagon.elf') as outelf, tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.hexagon.c') as outc:
      outc.write(self.prgstr)
      outc.flush()
      cc = f'{HEXAGON_SDK_PATH}/hexagon-clang'
      #cc = 'gcc'
      cmd= f'{cc} {outc.name} -O2 -Wall -xc -lm -DARGC={str(len(args)+1)} -o {outelf.name} '
      print(cmd)
      subprocess.check_output(args=cmd.split())

    if wait: st = time.monotonic()
    files = []
    for i,arg in enumerate(args):
      f = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{str(i)}.data.buf')
      f.write(arg._buf)
      files.append(f)
    #cmd = f'{outelf.name} '
    cmd = f'{HEXAGON_SDK_PATH}/hexagon-sim {outelf.name} -- '
    for f in files:
      cmd += f' {f.name} '
    for f in files:
      f.flush()
      f.close()
    subprocess.check_output(args=cmd.split())
    import array
    r = pathlib.Path(files[0].name).read_bytes()
    arr = array.array('f')
    arr.frombytes(r)
    for i,f in enumerate(arr):
      args[0]._buf[i] = f

    if wait: return time.monotonic()-st

renderer = functools.partial(uops_to_cstyle, CStyleLanguage(kernel_prefix=args['exp'], buffer_suffix=" restrict", arg_int_prefix="const int"))
HexagonBuffer = Compiled(RawMallocBuffer, LinearizerOptions(supports_float4=False, has_local=False), renderer, HexagonProgram)
