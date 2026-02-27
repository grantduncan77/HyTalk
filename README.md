+# HyTalk - Yaesu FT-710 CAT 多旋钮控制器（Raspberry Pi Zero 2 W）
+
+本版本按你的硬件目标设计：
+
+## 0. 主控硬件
+
+- 主控固定为 **树莓派 Zero 2 W（你说的“树莓派2zw”）**；
+- 建议使用稳定 5V 供电并为串口设备单独供电/共地；
+- 若启用大量外设（LCD 触摸 + 5 个编码器 + 4 个 OLED），建议加 I2C 上拉与电源滤波。
+
+- **4 个操作旋钮**（每个旋钮带按键）；
+- **1 个配置旋钮**（用于菜单配置）；
+- **1 块陶晶驰 2.4 寸串口 TFT 触摸液晶屏（320×240）**（菜单 + 运行信息）；
+- **4 块 OLED 点阵屏（0.91 寸 IIC 四针，128×32）**（每个操作旋钮一块，显示当前功能与值）。
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
+### LCD（陶晶驰2.4寸串口TFT触摸屏，320×240）
+
+- 菜单模式：显示“当前选中旋钮 + 待分配功能 + 可选列表”；
+- 运行模式：默认显示电台信息页（如发射功率、SWR、S 表）；
+- **配置模式超时**：配置旋钮 10 秒无操作将自动退出菜单并返回信息页；
+- **触屏切页**：在运行模式下触摸屏幕可切换当前显示内容（功率/SWR/S 表等）。
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
+## 3. 安装（Zero 2 W）
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
+- LCD/OLED 型号与总线（`display.*`，本例 LCD 为陶晶驰 2.4 寸串口 TFT 触摸屏 320×240，OLED 为 0.91 寸 IIC 四针 128×32）
+- 菜单超时（`runtime.menu_idle_timeout_s`，默认 10 秒）
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
+- 接入真实屏幕时，替换 `LcdDisplay` / `OledDisplay` 的渲染实现即可（LCD 按陶晶驰串口屏协议适配；OLED 推荐 SSD1306 0.91" 128×32 IIC 四针模块）；
+- 本版本会校验旋钮数量必须是 **4 个 operation + 1 个 config**。
 
EOF
)
