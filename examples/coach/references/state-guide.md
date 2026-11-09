## 何时读本文件

需要实现可中断续聊或排查状态问题时读取。

运行期状态写入 out/sessions/<slug>/<session_id>/state.json；技能包内只放 state/schema.json 与 scripts/state_io.py，保持只读。
