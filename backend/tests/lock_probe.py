"""test_collect_classify가 하위 프로세스로만 돌리는 파일(test_ 접두사가 없어 기본 수집에서 빠진다).
거래일 실행 잠금을 잡고 locked를 찍은 뒤 죽을 때까지 기다린다. 사용법: python tests/lock_probe.py 2026-10-16"""

import sys
import time
from datetime import date

from m30.config import load_settings
from m30.db.store import CardStore, connect

if __name__ == "__main__":
    with connect(load_settings()) as conn, CardStore(conn).run_lock(date.fromisoformat(sys.argv[1])):
        print("locked", flush=True)
        time.sleep(600)  # 부모가 SIGKILL로 끝낸다
