"""CAPTCHA 识别与自动绕过模块。

采用 图像理解 + 模拟鼠标点击 的方式完成 reCAPTCHA 图片验证。

流程：
  1. 点击 "I'm not a robot" 复选框，触发图片验证题目
  2. 截取验证题目区域图片
  3. 识别子图网格（3x3 / 4x4），标注编号
  4. 调用远程视觉理解大模型，识别应点击的格子
  5. 模拟鼠标点击对应格子
  6. 点击 Verify 按钮完成验证
"""

from .bypass import CaptchaBypass
from .solver import CaptchaSolver, GridAnnotator

__all__ = ["CaptchaBypass", "CaptchaSolver", "GridAnnotator"]
