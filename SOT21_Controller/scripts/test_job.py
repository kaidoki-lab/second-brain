"""接続テスト用のダミー処理。SOT21 の [Python処理実行] から呼ばれる。"""

import datetime
import platform
import sys

print("SOT21 TEST JOB")
print("time     :", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("host     :", platform.node())
print("python   :", sys.version.split()[0])
print("result   : OK")
