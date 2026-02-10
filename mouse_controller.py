"""
Низкоуровневый контроллер мыши через WinAPI SendInput
для инжекции сырых событий мыши на уровне ОС
"""

import ctypes
import ctypes.wintypes
import time
import math

class MouseController:
    def __init__(self):
        # Загрузка user32.dll
        self.user32 = ctypes.windll.user32
        
        # Константы
        self.MOUSE_MAX = 32767  # Максимальное значение для относительного движения
        self.MOUSEEVENTF_MOVE = 0x0001
        self.MOUSEEVENTF_LEFTDOWN = 0x0002
        self.MOUSEEVENTF_LEFTUP = 0x0004
        self.MOUSEEVENTF_RIGHTDOWN = 0x0008
        self.MOUSEEVENTF_RIGHTUP = 0x0010
        self.MOUSEEVENTF_MIDDLEDOWN = 0x0020
        self.MOUSEEVENTF_MIDDLEUP = 0x0040
        self.MOUSEEVENTF_ABSOLUTE = 0x8000
        self.MOUSEEVENTF_WHEEL = 0x0800
        self.MOUSEEVENTF_HWHEEL = 0x01000
        
        # Структуры Windows API
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
            ]
        
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
            ]
        
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)
            ]
        
        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT),
                       ("ki", KEYBDINPUT),
                       ("hi", HARDWAREINPUT)]
        
        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_ulong),
                ("union", INPUT_UNION)
            ]
        
        self.INPUT = INPUT
        self.MOUSEINPUT = MOUSEINPUT
        self.INPUT_UNION = INPUT_UNION
        
        # Кэшируем размер экрана
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)
    
    def _send_input(self, *inputs):
        """Отправка сырых событий ввода"""
        nInputs = len(inputs)
        pInputs = (self.INPUT * nInputs)(*inputs)
        cbSize = ctypes.sizeof(self.INPUT)
        return self.user32.SendInput(nInputs, ctypes.byref(pInputs), cbSize)
    
    def move_mouse(self, dx, dy):
        """
        Относительное перемещение мыши
        dx, dy - смещение в пикселях (относительно текущей позиции)
        """
        # Ограничиваем смещение для предотвращения переполнения
        dx = max(-self.MOUSE_MAX, min(self.MOUSE_MAX, dx))
        dy = max(-self.MOUSE_MAX, min(self.MOUSE_MAX, dy))
        
        # Создаем структуру для относительного движения
        inp = self.INPUT(
            type=0,  # INPUT_MOUSE
            union=self.INPUT_UNION(
                mi=self.MOUSEINPUT(
                    dx, 
                    dy, 
                    0, 
                    self.MOUSEEVENTF_MOVE, 
                    0, 
                    None
                )
            )
        )
        
        self._send_input(inp)
    
    def move_mouse_absolute(self, x, y):
        """
        Абсолютное перемещение мыши
        x, y - абсолютные координаты на экране
        """
        # Конвертируем координаты в системные единицы (0-65535)
        nx = int(x * 65536 / self.screen_width)
        ny = int(y * 65536 / self.screen_height)
        
        # Создаем структуру для абсолютного движения
        inp = self.INPUT(
            type=0,  # INPUT_MOUSE
            union=self.INPUT_UNION(
                mi=self.MOUSEINPUT(
                    nx, 
                    ny, 
                    0, 
                    self.MOUSEEVENTF_ABSOLUTE | self.MOUSEEVENTF_MOVE, 
                    0, 
                    None
                )
            )
        )
        
        self._send_input(inp)
    
    def move_mouse_to(self, x, y, duration=0.0):
        """
        Плавное перемещение мыши в абсолютные координаты
        x, y - целевые координаты
        duration - время перемещения в секундах
        """
        # Получаем текущую позицию мыши
        current_x, current_y = self.get_position()
        
        if duration <= 0:
            # Мгновенное перемещение
            self.move_mouse_absolute(x, y)
        else:
            # Плавное перемещение с разбивкой на шаги
            steps = max(2, int(duration * 100))  # 100 шагов в секунду
            step_x = (x - current_x) / steps
            step_y = (y - current_y) / steps
            step_delay = duration / steps
            
            for i in range(steps):
                target_x = current_x + step_x * i
                target_y = current_y + step_y * i
                self.move_mouse_absolute(int(target_x), int(target_y))
                time.sleep(step_delay)
            
            # Финальный шаг для точного позиционирования
            self.move_mouse_absolute(x, y)
    
    def mouse_down(self, button='left'):
        """Нажатие кнопки мыши"""
        flags = 0
        if button == 'left':
            flags = self.MOUSEEVENTF_LEFTDOWN
        elif button == 'right':
            flags = self.MOUSEEVENTF_RIGHTDOWN
        elif button == 'middle':
            flags = self.MOUSEEVENTF_MIDDLEDOWN
        
        inp = self.INPUT(
            type=0,
            union=self.INPUT_UNION(
                mi=self.MOUSEINPUT(0, 0, 0, flags, 0, None)
            )
        )
        self._send_input(inp)
    
    def mouse_up(self, button='left'):
        """Отпускание кнопки мыши"""
        flags = 0
        if button == 'left':
            flags = self.MOUSEEVENTF_LEFTUP
        elif button == 'right':
            flags = self.MOUSEEVENTF_RIGHTUP
        elif button == 'middle':
            flags = self.MOUSEEVENTF_MIDDLEUP
        
        inp = self.INPUT(
            type=0,
            union=self.INPUT_UNION(
                mi=self.MOUSEINPUT(0, 0, 0, flags, 0, None)
            )
        )
        self._send_input(inp)
    
    def click(self, button='left', duration=0.1):
        """Клик мышью с задержкой между нажатием и отпусканием"""
        self.mouse_down(button)
        time.sleep(duration)
        self.mouse_up(button)
    
    def click_at(self, x, y, button='left', move_duration=0.0, click_duration=0.1):
        """Перемещение и клик"""
        self.move_mouse_to(x, y, move_duration)
        self.click(button, click_duration)
    
    def drag(self, start_x, start_y, end_x, end_y, button='left', duration=1.0):
        """Перетаскивание мышью"""
        # Перемещаем к начальной точке
        self.move_mouse_to(start_x, start_y, duration/3)
        time.sleep(0.1)
        
        # Нажимаем кнопку
        self.mouse_down(button)
        time.sleep(0.2)
        
        # Перемещаем с зажатой кнопкой
        self.move_mouse_to(end_x, end_y, duration/3)
        time.sleep(0.1)
        
        # Отпускаем кнопку
        self.mouse_up(button)
    
    def scroll(self, clicks, direction='vertical'):
        """Прокрутка колесика мыши"""
        flags = self.MOUSEEVENTF_WHEEL if direction == 'vertical' else self.MOUSEEVENTF_HWHEEL
        # WHEEL_DELTA = 120, один "клик" = 120 единиц
        amount = clicks * 120
        
        inp = self.INPUT(
            type=0,
            union=self.INPUT_UNION(
                mi=self.MOUSEINPUT(0, 0, amount, flags, 0, None)
            )
        )
        self._send_input(inp)
    
    def get_position(self):
        """Получение текущей позиции мыши"""
        point = ctypes.wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y
    
    def get_screen_size(self):
        """Получение размеров экрана"""
        return self.screen_width, self.screen_height
    
    def smooth_move_rel(self, dx, dy, duration=1.0):
        """
        Плавное относительное перемещение
        Разбивает большое движение на несколько маленьких шагов
        """
        steps = max(2, int(duration * 100))
        step_delay = duration / steps
        
        # Разбиваем общее смещение на шаги
        step_x = dx / steps
        step_y = dy / steps
        
        for i in range(steps):
            # Ограничиваем каждый шаг
            step_dx = int(step_x)
            step_dy = int(step_y)
            
            if step_dx != 0 or step_dy != 0:
                self.move_mouse(step_dx, step_dy)
            
            time.sleep(step_delay)
        
        # Корректируем остаток
        remainder_x = dx - (step_x * steps)
        remainder_y = dy - (step_y * steps)
        
        if remainder_x != 0 or remainder_y != 0:
            self.move_mouse(int(remainder_x), int(remainder_y))
