 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/README.md b/README.md
new file mode 100644
index 0000000000000000000000000000000000000000..3d79983e7dd9499fb3c0432765c1f138cf861795
--- /dev/null
+++ b/README.md
@@ -0,0 +1,77 @@
+# HyTalk - Yaesu FT-710 CAT 多旋钮控制器（Raspberry Pi）
+
+本版本按你的硬件目标设计：
+
+- **4 个操作旋钮**（每个旋钮带按键）；
+- **1 个配置旋钮**（用于菜单配置）；
+- **1 块 2.8 寸彩色 LCD**（菜单 + 运行信息）；
+- **4 块 OLED 点阵屏**（每个操作旋钮一块，显示当前功能与值）。
+
+## 1. 系统功能
+
+### 操作旋钮（4个）
+
+- 每个操作旋钮并不固定功能，而是可以被映射为：
+  - VFO 频率
+  - AF 增益
+  - RF 增益
+  - MIC 增益
+  - 发射功率
+  - （可扩展更多 profile）
+- 每个操作旋钮的 OLED 实时显示：
+  - 当前 profile 名称（功能）
+  - 当前值（例如频率/增益/功率）
+
+### 配置旋钮（1个）
+
+- 按下进入 LCD 菜单；
+- 旋转选择要配置的操作旋钮；
+- 再按一下切换到功能 profile 选择；
+- 再按一下确认分配并退出菜单。
+
+### LCD（2.8寸）
+
+- 菜单模式：显示“当前选中旋钮 + 待分配功能 + 可选列表”；
+- 运行模式：轮询显示电台信息页（如发射功率、SWR、S 表）。
+
+## 2. FT-710 CAT 编码说明
+
+- 使用 `cat.protocol: ft710`；
+- 命令必须以 2 位大写命令头开头（例如 `FA`、`AG`、`RG`、`PC`、`MG`）；
+- 结尾由程序补 `;`；
+- 位宽按 CAT 手册做模板格式化，例如：
+  - `FA{vfo_a_hz:011d}`（11 位频率字段）
+  - `PC{tx_power_set:03d}`（3 位数值字段）
+
+## 3. 安装
+
+```bash
+python3 -m venv .venv
+source .venv/bin/activate
+pip install -r requirements.txt
+```
+
+## 4. 配置
+
+```bash
+cp config/knobs.example.yaml config/knobs.yaml
+```
+
+然后修改：
+
+- 串口参数（`serial.*`）
+- GPIO 引脚（`knobs[].pins`）
+- LCD/OLED 型号与总线（`display.*`）
+- 功能 profile 和默认分配（`display.oled.profiles` / `default_assignments`）
+
+## 5. 运行
+
+```bash
+python app/yaesu_cat_knobs.py --config config/knobs.yaml
+```
+
+## 6. 说明
+
+- 当前 LCD/OLED 为**抽象层**，默认以日志方式输出，便于先跑通控制逻辑；
+- 接入真实屏幕时，替换 `LcdDisplay` / `OledDisplay` 的渲染实现即可；
+- 本版本会校验旋钮数量必须是 **4 个 operation + 1 个 config**。
 
EOF
)
