
import time
import cv2
import numpy as np
import pyautogui  # Только для скриншотов!
import keyboard
import random
import os
import ctypes
import ctypes.wintypes
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import traceback
import threading


# =========================
# Совместимость ULONG_PTR
# =========================
if hasattr(ctypes.wintypes, "ULONG_PTR"):
    ULONG_PTR = ctypes.wintypes.ULONG_PTR
else:
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


# =========================
# ctypes структуры WinAPI (СНАРУЖИ, не внутри класса!)
# =========================

INPUT_MOUSE = 0

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("union", INPUT_UNION)]


# =========================
# ДАТАКЛАССЫ
# =========================

@dataclass
class ItemGrade:
    """Класс для грейда предмета"""
    path: str
    break_it: bool = False
    last_found_time: float = 0
    found_count: int = 0


@dataclass
class ItemData:
    """Класс для данных предмета"""
    name: str
    grades: List[ItemGrade]
    crafted_count: int = 0

    def get_break_grades(self) -> List[ItemGrade]:
        return [grade for grade in self.grades if grade.break_it]

    def get_craft_grades(self) -> List[ItemGrade]:
        return [grade for grade in self.grades if not grade.break_it]


# =========================
# WinAPI SendInput мышь
# =========================

class WinAPIMouseController:
    user32 = ctypes.windll.user32
    MOUSE_MAX = 32767

    def __init__(self):
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)

    def _send_input(self, *inputs):
        nInputs = len(inputs)
        pInputs = (INPUT * nInputs)(*inputs)
        cbSize = ctypes.sizeof(INPUT)
        return self.user32.SendInput(nInputs, ctypes.byref(pInputs), cbSize)

    def get_position(self):
        point = ctypes.wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def get_screen_size(self):
        return self.screen_width, self.screen_height

    def move_mouse(self, dx, dy):
        dx = max(-self.MOUSE_MAX, min(self.MOUSE_MAX, int(dx)))
        dy = max(-self.MOUSE_MAX, min(self.MOUSE_MAX, int(dy)))

        inp = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)),
        )
        self._send_input(inp)

    def move_mouse_absolute(self, x, y):
        x = int(x)
        y = int(y)

        nx = int(x * 65535 / max(1, (self.screen_width - 1)))
        ny = int(y * 65535 / max(1, (self.screen_height - 1)))

        inp = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE, 0, 0)
            ),
        )
        self._send_input(inp)

    def move_mouse_to(self, x, y, duration=0.0):
        current_x, current_y = self.get_position()
        if duration <= 0:
            self.move_mouse_absolute(x, y)
            return

        steps = max(2, int(duration * 100))
        step_x = (x - current_x) / steps
        step_y = (y - current_y) / steps
        step_delay = duration / steps

        for i in range(steps):
            tx = current_x + step_x * (i + 1)
            ty = current_y + step_y * (i + 1)
            self.move_mouse_absolute(int(tx), int(ty))
            time.sleep(step_delay)

    def smooth_move_rel(self, dx, dy, duration=1.0):
        steps = max(2, int(duration * 100))
        step_delay = duration / steps
        step_x = dx / steps
        step_y = dy / steps

        for i in range(steps):
            current_step_x = int(step_x * (i + 1)) - int(step_x * i)
            current_step_y = int(step_y * (i + 1)) - int(step_y * i)

            if current_step_x != 0 or current_step_y != 0:
                self.move_mouse(current_step_x, current_step_y)

            time.sleep(step_delay)

    def mouse_down(self, button="left"):
        if button == "left":
            flags = MOUSEEVENTF_LEFTDOWN
        elif button == "right":
            flags = MOUSEEVENTF_RIGHTDOWN
        else:
            flags = MOUSEEVENTF_MIDDLEDOWN

        inp = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, flags, 0, 0)),
        )
        self._send_input(inp)

    def mouse_up(self, button="left"):
        if button == "left":
            flags = MOUSEEVENTF_LEFTUP
        elif button == "right":
            flags = MOUSEEVENTF_RIGHTUP
        else:
            flags = MOUSEEVENTF_MIDDLEUP

        inp = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, flags, 0, 0)),
        )
        self._send_input(inp)

    def click(self, button="left", duration=0.05):
        self.mouse_down(button)
        time.sleep(duration)
        self.mouse_up(button)

    def click_at(self, x, y, button="left", move_duration=0.0, click_duration=0.05):
        self.move_mouse_to(x, y, move_duration)
        self.click(button, click_duration)


# =========================
# ЯДРО БОТА
# =========================

class CraftBotCore:
    def __init__(
        self,
        create_button_path,
        region,
        items,
        create_delay=2.0,
        click_delay=0.3,
        threshold=0.75,
        break_count=10,
        turn_delay=1.0,
        auto_break=True,
        gui_callback=None,
        log_callback=None,
        turn_pixels=500,
        inventory_region=None,
        break_slots_region=None,
        break_slots_target=0,
        no_resources_path=None,
    ):
        # ✅ коллбэки
        self.gui_callback = gui_callback
        self.log_callback = log_callback

        # --- основные параметры ---
        self.create_button_path = create_button_path
        self.region = region
        self.items = self._convert_items_dict(items)

        self.create_delay = float(create_delay)
        self.click_delay = float(click_delay)
        self.break_count = int(break_count)
        self.turn_delay = float(turn_delay)
        self.turn_pixels = int(turn_pixels)
        self.inventory_region = inventory_region
        self.break_slots_region = break_slots_region
        self.break_slots_target = max(0, int(break_slots_target))
        self.auto_break = auto_break

        # --- threshold (КРИТИЧНО!) ---
        try:
            self.threshold = float(threshold)
            if self.threshold > 1:
                self.threshold = self.threshold / 100.0
        except Exception:
            self.threshold = 0.9

        self.log(f"🎯 Threshold установлен: {self.threshold}", "INFO")

        # --- проверка ресурсов ---
        self.no_resources_path = no_resources_path
        self.no_resources_img = None

        if no_resources_path and os.path.exists(no_resources_path):
            try:
                self.no_resources_img = cv2.imread(no_resources_path)
                if self.no_resources_img is not None:
                    self.log(
                        f"✅ Загружено изображение проверки ресурсов: {os.path.basename(no_resources_path)}",
                        "SUCCESS",
                    )
                else:
                    self.log(
                        f"❌ Не удалось загрузить изображение проверки ресурсов: {no_resources_path}",
                        "ERROR",
                    )
            except Exception as e:
                self.log(
                    f"❌ Ошибка загрузки изображения проверки ресурсов: {str(e)}",
                    "ERROR",
                )

        # --- логика пустых крафтов ---
        self.empty_craft_threshold = 3
        self.consecutive_empty_crafts = 0

        # --- состояние бота ---
        self.running = False
        self.paused = False
        self.break_thread = None
        self.break_in_progress = False

        # --- счётчики ---
        self.crafted_count = 0
        self.broken_count = 0
        self.cycle_count = 0
        self.errors_count = 0
        self.successful_cycles = 0
        self.break_attempts = 0

        # --- мышь ---
        try:
            self.mouse = WinAPIMouseController()
            self.use_winapi_mouse = True
            self.log("✅ Используем WinAPI SendInput для управления мышью", "SUCCESS")
        except Exception as e:
            self.mouse = None
            self.use_winapi_mouse = False
            self.log(
                f"⚠️ Не удалось инициализировать WinAPI мышь: {str(e)}",
                "WARNING",
            )
            self.log("⚠️ Используем pyautogui для управления мышью", "WARNING")

        # --- кнопка создания ---
        self.create_button_img = None
        if os.path.exists(create_button_path):
            try:
                self.create_button_img = cv2.imread(create_button_path)
                if self.create_button_img is None:
                    self.log(
                        f"❌ Не удалось загрузить изображение кнопки: {create_button_path}",
                        "ERROR",
                    )
            except Exception as e:
                self.log(
                    f"❌ Ошибка загрузки кнопки: {str(e)}",
                    "ERROR",
                )
        else:
            self.log(
                f"❌ Файл кнопки не найден: {create_button_path}",
                "ERROR",
            )

        # --- таймеры ---
        self.last_activity_time = time.time()
        self.start_time = time.time()

    # ---------- items ----------
    def _find_same_item_near(self, grade_path, last_pos, max_distance=40):
        """
        Ищет ТОТ ЖЕ предмет рядом с предыдущей позицией.
        Возвращает (x, y) или None
        """
        positions = self.find_image(
            grade_path,
            search_region=self.inventory_region,
            confidence=self.threshold * 0.95
        )

        if not positions:
            return None

        lx, ly = last_pos

        for x, y in positions:
            if math.hypot(x - lx, y - ly) <= max_distance:
                return (x, y)

        return None

    def _convert_items_dict(self, items_dict: Dict) -> List[ItemData]:
        items_list = []
        for name, item_data in items_dict.items():
            grades = []
            for grade_dict in item_data.get("grades", []):
                grades.append(
                    ItemGrade(
                        path=grade_dict.get("path", ""),
                        break_it=grade_dict.get("break", False),
                    )
                )
            items_list.append(
                ItemData(
                    name=name,
                    grades=grades,
                    crafted_count=item_data.get("count", 0),
                )
            )
        return items_list

    # ---------- logging ----------

    def log(self, message: str, level: str = "INFO"):
        if self.log_callback:
            try:
                self.log_callback(message, level)
                return
            except Exception:
                pass

        timestamp = time.strftime("%H:%M:%S")
        level_icon = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "DEBUG": "🔍",
        }.get(level, "ℹ️")
        print(f"[{timestamp}] {level_icon} {message}")

    def count_break_items_in_region(self, target_region: Optional[Tuple[int, int, int, int]]) -> int:
        """Считает количество предметов для разбора в указанной области."""
        if not target_region:
            return 0

        x, y, w, h = target_region

        screenshot = pyautogui.screenshot(region=target_region)
        screenshot_np = np.array(screenshot)
        screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

        # В слотах дробилки иконки часто отличаются по яркости/контрасту от инвентаря.
        # Делаем порог чуть мягче, чтобы не занижать подсчет занятых слотов.
        slot_threshold = max(0.55, self.threshold * 0.8)

        results: List[Tuple[int, int]] = []
        min_template_size = None

        for item in self.items:
            for grade in item.grades:
                if not grade.break_it or not os.path.exists(grade.path):
                    continue

                template = cv2.imread(grade.path)
                if template is None:
                    continue

                h_t, w_t = template.shape[:2]
                current_size = min(h_t, w_t)
                min_template_size = current_size if min_template_size is None else min(min_template_size, current_size)
                result = cv2.matchTemplate(screenshot_cv, template, cv2.TM_CCOEFF_NORMED)
                locations = np.where(result >= slot_threshold)

                for pt in zip(*locations[::-1]):
                    cx = x + pt[0] + w_t // 2
                    cy = y + pt[1] + h_t // 2
                    results.append((int(cx), int(cy)))

        # Для плотной сетки слотов дробилки (иконки близко друг к другу)
        # используем меньший радиус дедупликации, чтобы не "склеивать" соседние слоты.
        dedupe_radius = 8
        if min_template_size:
            dedupe_radius = max(6, int(min_template_size * 0.35))

        unique = []
        for p in results:
            if not any(math.hypot(p[0] - u[0], p[1] - u[1]) < dedupe_radius for u in unique):
                unique.append(p)

        self.log(
            f"🧮 Подсчет слотов дробилки: найдено {len(unique)} (raw={len(results)}; thr={slot_threshold:.2f}; r={dedupe_radius})",
            "DEBUG",
        )

        return len(unique)
    def find_all_break_items(self) -> List[Tuple[int, int]]:
        """
        Ищет ВСЕ предметы всех грейдов, помеченных break_it=True,
        за ОДИН проход по скриншоту инвентаря.
        """
        results = []

        if not self.inventory_region:
            return results

        x, y, w, h = self.inventory_region

        screenshot = pyautogui.screenshot(region=self.inventory_region)
        screenshot_np = np.array(screenshot)
        screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

        for item in self.items:
            for grade in item.grades:
                if not grade.break_it or not os.path.exists(grade.path):
                    continue

                template = cv2.imread(grade.path)
                if template is None:
                    continue

                h_t, w_t = template.shape[:2]

                result = cv2.matchTemplate(
                    screenshot_cv,
                    template,
                    cv2.TM_CCOEFF_NORMED
                )

                locations = np.where(result >= self.threshold)

                for pt in zip(*locations[::-1]):
                    cx = x + pt[0] + w_t // 2
                    cy = y + pt[1] + h_t // 2
                    results.append((int(cx), int(cy)))

        # убираем дубликаты по расстоянию
        unique = []
        for p in results:
            if not any(math.hypot(p[0]-u[0], p[1]-u[1]) < 20 for u in unique):
                unique.append(p)

        return unique

    def update_gui(self):
        if self.gui_callback:
            try:
                self.gui_callback(self.crafted_count, self.broken_count, self.cycle_count)
            except Exception as e:
                self.log(f"Ошибка обновления GUI: {str(e)}", "ERROR")

    # ---------- resources check ----------

    def check_resources_available(self) -> bool:
        if self.no_resources_img is not None:
            try:
                screenshot = pyautogui.screenshot()
                screenshot_np = np.array(screenshot)
                screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

                result = cv2.matchTemplate(screenshot_cv, self.no_resources_img, cv2.TM_CCOEFF_NORMED)
                locations = np.where(result >= self.threshold * 0.9)

                if len(locations[0]) > 0:
                    self.log(f"⚠️ Обнаружено отсутствие ресурсов ({len(locations[0])} совпадений)", "WARNING")
                    return False
            except Exception as e:
                self.log(f"Ошибка при проверке ресурсов: {str(e)}", "ERROR")

        create_positions = self.find_image(self.create_button_path, confidence=self.threshold * 0.7)
        if not create_positions:
            self.log("⚠️ Кнопка 'Создать' не найдена, возможно нет ресурсов", "WARNING")
            return False

        return True

    # ---------- image search ----------

    def find_image(self, template_path: str, search_region: Optional[Tuple] = None,
                   confidence: Optional[float] = None) -> List[Tuple[int, int]]:
        try:
            if not os.path.exists(template_path):
                self.log(f"Файл не найден: {template_path}", "WARNING")
                return []

            template = cv2.imread(template_path)
            if template is None:
                self.log(f"Не удалось загрузить изображение: {template_path}", "WARNING")
                return []

            try:
                screenshot = pyautogui.screenshot(region=search_region) if search_region else pyautogui.screenshot()
            except Exception as e:
                self.log(f"Ошибка при создании скриншота: {str(e)}", "ERROR")
                return []

            screenshot_np = np.array(screenshot)
            screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

            threshold = confidence if confidence is not None else self.threshold

            result = cv2.matchTemplate(screenshot_cv, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)

            matches = []
            h, w = template.shape[:2]

            for pt in zip(*locations[::-1]):
                cx = pt[0] + w // 2
                cy = pt[1] + h // 2
                if search_region:
                    cx += search_region[0]
                    cy += search_region[1]
                matches.append((int(cx), int(cy)))

            unique_matches = []
            for match in matches:
                dup = False
                for unique in unique_matches:
                    if math.hypot(match[0] - unique[0], match[1] - unique[1]) < max(w, h) * 0.5:
                        dup = True
                        break
                if not dup:
                    unique_matches.append(match)

            return unique_matches

        except Exception as e:
            self.log(f"Ошибка поиска изображения {os.path.basename(template_path)}: {str(e)}", "ERROR")
            return []

    # ---------- mouse helpers ----------

    def move_mouse_to_center(self):
        try:
            if self.use_winapi_mouse and self.mouse:
                screen_width, screen_height = self.mouse.get_screen_size()
            else:
                screen_width, screen_height = pyautogui.size()

            cx = screen_width // 2
            cy = screen_height // 2

            if self.use_winapi_mouse and self.mouse:
                self.mouse.move_mouse_to(cx, cy, duration=0.5)
            else:
                pyautogui.moveTo(cx, cy, duration=0.5)

            time.sleep(0.3)
            self.log(f"Мышь перемещена в центр: ({cx}, {cy})", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Ошибка перемещения мыши: {str(e)}", "ERROR")
            return False

    def turn_character(self, direction: str = "left", pixels: Optional[int] = None, hold_rmb: bool = False) -> bool:
        try:
            if pixels is None:
                pixels = self.turn_pixels
            if direction == "right":
                pixels = -pixels

            self.log(f"Поворачиваем персонажа на {abs(pixels)} пикселей в {direction} (ПКМ={'да' if hold_rmb else 'нет'})", "INFO")

            # ВАЖНО: не жмём ПКМ, если он не нужен
            if hold_rmb:
                if self.use_winapi_mouse and self.mouse:
                    self.mouse.mouse_down(button="right")
                else:
                    pyautogui.mouseDown(button="right")
                time.sleep(0.02)  # если уж держим, то минимально

            # Двигаем мышь относительным смещением
            if self.use_winapi_mouse and self.mouse:
                self.mouse.smooth_move_rel(pixels, 0, duration=self.turn_delay)
            else:
                steps = max(10, int(self.turn_delay * 60))
                step_distance = pixels / steps
                for _ in range(steps):
                    pyautogui.moveRel(step_distance, 0, duration=self.turn_delay / steps)

            if hold_rmb:
                if self.use_winapi_mouse and self.mouse:
                    self.mouse.mouse_up(button="right")
                else:
                    pyautogui.mouseUp(button="right")

            time.sleep(0.1)
            self.log(f"Поворот завершен на {abs(pixels)} пикселей", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Ошибка при повороте: {str(e)}", "ERROR")
            return False

    # ---------- open craft interface ----------

    def open_craft_interface(self) -> bool:
        self.log("Пытаемся открыть интерфейс крафта...", "INFO")

        try:
            
            time.sleep(0.5)

            keyboard.press_and_release("e")
            time.sleep(2.0)

            if self.find_image(self.create_button_path):
                self.log("Интерфейс крафта успешно открыт", "SUCCESS")
                return True

            self.log("Интерфейс не открылся, пробуем еще раз...", "WARNING")
            keyboard.press_and_release("esc")
            time.sleep(1.0)

            keyboard.press_and_release("e")
            time.sleep(2.0)

            if self.find_image(self.create_button_path):
                self.log("Интерфейс крафта успешно открыт со второй попытки", "SUCCESS")
                return True

            self.log("Не удалось открыть интерфейс крафта", "ERROR")
            return False

        except Exception as e:
            self.log(f"Ошибка при открытии интерфейса крафта: {str(e)}", "ERROR")
            return False

    # ---------- collect items ----------
    def _same_position(self, p1, p2, tolerance=6):
        """Проверка: почти та же позиция (для определения полной дробилки)"""
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= tolerance

    def collect_items(self) -> bool:
        if not self.region:
            self.log("Не задана область для сбора предметов", "WARNING")
            return False

        x, y, w, h = self.region
        items_collected = 0

        self.log("🔍 Итеративный сбор предметов (клик → проверка)", "INFO")

        while self.running:
            screenshot = pyautogui.screenshot(region=self.region)
            screenshot_np = np.array(screenshot)
            screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

            found_any = False

            for item in self.items:
                for grade in item.grades:
                    if not os.path.exists(grade.path):
                        continue

                    template = cv2.imread(grade.path)
                    if template is None:
                        continue

                    h_t, w_t = template.shape[:2]

                    result = cv2.matchTemplate(
                        screenshot_cv,
                        template,
                        cv2.TM_CCOEFF_NORMED
                    )

                    locations = np.where(result >= self.threshold * 0.65)

                    for pt in zip(*locations[::-1]):
                        cx = x + pt[0] + w_t // 2
                        cy = y + pt[1] + h_t // 2

                        try:
                            if self.use_winapi_mouse and self.mouse:
                                self.mouse.click_at(
                                    cx,
                                    cy,
                                    button="right",
                                    move_duration=0.05
                                )
                            else:
                                pyautogui.rightClick(cx, cy)

                            items_collected += 1
                            self.crafted_count += 1
                            self.update_gui()

                            time.sleep(self.click_delay)

                            found_any = True
                            break

                        except Exception as e:
                            self.log(
                                f"Ошибка клика по предмету: {str(e)}",
                                "ERROR"
                            )

                    if found_any:
                        break
                if found_any:
                    break

            if not found_any:
                break

        if items_collected > 0:
            self.log(
                f"✅ Сбор завершён, собрано предметов: {items_collected}",
                "SUCCESS"
            )
            return True
        else:
            self.log("ℹ️ Предметы для сбора не найдены", "INFO")
            return False


    # ---------- break items ----------
    def find_all_break_items(self) -> List[Tuple[int, int]]:
        """
        Ищет ВСЕ предметы всех грейдов, помеченных break_it=True,
        и логирует, сколько найдено каждого грейда.
        """
        results = []

        if not self.inventory_region:
            self.log("❌ inventory_region не задан", "ERROR")
            return results

        x, y, w, h = self.inventory_region

        screenshot = pyautogui.screenshot(region=self.inventory_region)
        screenshot_np = np.array(screenshot)
        screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)

        self.log(
            f"📦 Инвентарь: {w}x{h}, threshold={self.threshold}",
            "DEBUG"
        )

        total_found = 0

        for item in self.items:
            for grade in item.grades:
                if not grade.break_it:
                    continue

                if not os.path.exists(grade.path):
                    self.log(f"❌ Файл шаблона не найден: {grade.path}", "ERROR")
                    continue

                template = cv2.imread(grade.path)
                if template is None:
                    self.log(f"❌ Не удалось загрузить шаблон: {grade.path}", "ERROR")
                    continue

                h_t, w_t = template.shape[:2]

                result = cv2.matchTemplate(
                    screenshot_cv,
                    template,
                    cv2.TM_CCOEFF_NORMED
                )

                locations = np.where(result >= self.threshold)
                found_count = len(locations[0])

                self.log(
                    f"🔍 Грейд {os.path.basename(grade.path)} | "
                    f"найдено: {found_count} | "
                    f"шаблон: {w_t}x{h_t}",
                    "INFO"
                )

                for pt in zip(*locations[::-1]):
                    cx = x + pt[0] + w_t // 2
                    cy = y + pt[1] + h_t // 2
                    results.append((int(cx), int(cy)))
                    total_found += 1

        # Убираем дубликаты
        unique = []
        for p in results:
            if not any(math.hypot(p[0] - u[0], p[1] - u[1]) < 20 for u in unique):
                unique.append(p)

        self.log(
            f"📊 ИТОГО найдено предметов: {len(unique)} (сырых совпадений: {total_found})",
            "INFO"
        )

        return unique

    def break_items_thread(self) -> bool:
        self.break_in_progress = True

        try:
            self.log("=== НАЧАЛО ПРОЦЕДУРЫ РАЗБОРА ===", "INFO")

            keyboard.press_and_release("e")
            time.sleep(2.0)

            keyboard.press_and_release("i")
            time.sleep(2.0)

            items_broken = 0
            slots_control_enabled = bool(self.break_slots_region and self.break_slots_target > 0)

            if slots_control_enabled:
                self.log(
                    f"🧩 Контроль слотов дробилки включен: цель {self.break_slots_target}",
                    "INFO"
                )

            while self.running:
                if slots_control_enabled:
                    current_slots_count = self.count_break_items_in_region(self.break_slots_region)
                    self.log(
                        f"📦 Слоты дробилки заняты: {current_slots_count}/{self.break_slots_target}",
                        "INFO"
                    )

                    if current_slots_count >= self.break_slots_target:
                        self.log("✅ Слоты дробилки заполнены, добавление из инвентаря не требуется", "INFO")
                        break

                positions = self.find_all_break_items()

                if not positions:
                    break

                pos = random.choice(positions)

                self.log(
                    f"🔨 Разбираем предмет в позиции {pos}",
                    "INFO"
                )

                if self.use_winapi_mouse and self.mouse:
                    self.mouse.click_at(
                        pos[0],
                        pos[1],
                        button="right",
                        move_duration=0.1
                    )
                else:
                    pyautogui.rightClick(pos[0], pos[1])

                time.sleep(0.8)

                items_broken += 1
                self.broken_count += 1
                self.update_gui()

                if slots_control_enabled:
                    new_slots_count = self.count_break_items_in_region(self.break_slots_region)
                    self.log(
                        f"🔄 После добавления: {new_slots_count}/{self.break_slots_target}",
                        "INFO"
                    )

                    if new_slots_count >= self.break_slots_target:
                        self.log("✅ Достигнуто нужное количество предметов в слотах дробилки", "SUCCESS")
                        break

            keyboard.press_and_release("esc")
            time.sleep(1.5)
            keyboard.press_and_release("esc")

            self.log(
                f"✅ Разбор завершён, разобрано: {items_broken}",
                "SUCCESS"
            )

            self.break_in_progress = False
            return items_broken > 0

        except Exception as e:
            self.log(f"❌ Ошибка разбора: {str(e)}", "ERROR")
            self.break_in_progress = False
            return False



    def start_break_items(self):
        if self.break_in_progress:
            self.log("Разбор уже выполняется", "WARNING")
            return False
        self.break_thread = threading.Thread(target=self.break_items_thread, daemon=True)
        self.break_thread.start()
        return True

    # ---------- craft cycle ----------

    def craft_cycle(self) -> bool:
        self.cycle_count += 1
        self.update_gui()

        self.log(f"=== ЦИКЛ КРАФТА №{self.cycle_count} ===", "INFO")

        try:
            # ✅ ВАЖНО: сначала всегда пытаемся собрать предметы
            # даже если кнопки "Создать" нет (вдруг предметы появились сами)
            self.log("🔍 Быстрая проверка: есть ли предметы в области (даже без 'Создать')...", "INFO")
            if self.collect_items():
                self.log("✅ Найдены/собраны предметы без нажатия 'Создать' — продолжаем цикл", "SUCCESS")
                # если предметы находятся - это НЕ пустой крафт
                self.consecutive_empty_crafts = 0
                return True

            # Далее обычная логика крафта
            self.log("Проверяем наличие ресурсов...", "INFO")
            if not self.check_resources_available():
                # ⛔ если ресурсов нет, но вдруг предметы появятся — попробуем собрать ещё раз
                self.log("⚠️ Ресурсов/кнопки нет. Доп.проверка предметов перед выходом...", "WARNING")
                if self.collect_items():
                    self.log("✅ На доп.проверке найдены предметы — собрали", "SUCCESS")
                    self.consecutive_empty_crafts = 0
                    return True

                self.consecutive_empty_crafts += 1
                self.log(
                    f"❌ Ресурсы для крафта отсутствуют "
                    f"(подряд: {self.consecutive_empty_crafts}/{self.empty_craft_threshold})",
                    "WARNING",
                )

                if self.consecutive_empty_crafts >= self.empty_craft_threshold:
                    self.log("⚠️ Достигнут порог пустых крафтов, требуется разбор", "ERROR")
                    return False

                time.sleep(2)
                return False

            self.consecutive_empty_crafts = 0

            # 🔘 Поиск кнопки «Создать»
            create_positions = self.find_image(self.create_button_path)

            if not create_positions:
                self.log("⚠️ Кнопка 'Создать' не найдена, пытаемся открыть интерфейс...", "WARNING")

                if not self.open_craft_interface():
                    # даже если интерфейс не открылся — ещё раз проверим предметы
                    self.log("❌ Не удалось открыть интерфейс крафта. Проверяем предметы напоследок...", "ERROR")
                    if self.collect_items():
                        self.log("✅ Нашли предметы даже без интерфейса — собрали", "SUCCESS")
                        return True
                    return False

                create_positions = self.find_image(self.create_button_path)
                if not create_positions:
                    self.log("❌ Кнопка 'Создать' всё ещё не найдена", "ERROR")
                    # и тут тоже финальная попытка сбора
                    if self.collect_items():
                        self.log("✅ Предметы найдены/собраны — продолжаем", "SUCCESS")
                        return True
                    return False

            create_x, create_y = create_positions[0]
            self.log(f"Найдена кнопка 'Создать' в позиции ({create_x}, {create_y})", "SUCCESS")

            # 🖱️ Клик по кнопке «Создать»
            if self.use_winapi_mouse and self.mouse:
                self.mouse.click_at(
                    create_x, create_y,
                    button="left",
                    move_duration=0.1,
                    click_duration=0.05
                )
            else:
                pyautogui.click(create_x, create_y)

            self.log(f"Кликнули на кнопку, ждём {self.create_delay} секунд...", "INFO")
            time.sleep(self.create_delay)

            # 🔄 Сбор предметов после крафта
            items_found = False

            for attempt in range(3):
                self.log(f"Попытка сбора предметов {attempt + 1}/3", "INFO")

                if self.collect_items():
                    items_found = True
                    self.log("✅ Предметы успешно собраны!", "SUCCESS")
                    break

                time.sleep(0.5)

            if not items_found:
                self.consecutive_empty_crafts += 1
                self.log(
                    f"⚠️ Предметы не найдены после создания "
                    f"(подряд: {self.consecutive_empty_crafts}/{self.empty_craft_threshold})",
                    "WARNING"
                )
            else:
                self.successful_cycles += 1
                self.consecutive_empty_crafts = 0

            if items_found:
                self.log(f"✅ Цикл крафта №{self.cycle_count} завершён успешно", "SUCCESS")
            else:
                self.log(f"ℹ️ Цикл крафта №{self.cycle_count} завершён без предметов", "INFO")

            return items_found

        except Exception as e:
            self.errors_count += 1
            self.log(f"❌ Ошибка в цикле крафта: {str(e)}", "ERROR")
            return False


    # ---------- stats / run ----------

    def get_statistics(self) -> Dict:
        current_time = time.time()
        elapsed_time = current_time - self.start_time

        success_rate = (self.successful_cycles / self.cycle_count * 100) if self.cycle_count > 0 else 0
        items_per_hour = (self.crafted_count / elapsed_time * 3600) if elapsed_time > 0 else 0

        return {
            "elapsed_time": elapsed_time,
            "cycles": self.cycle_count,
            "successful_cycles": self.successful_cycles,
            "crafted_items": self.crafted_count,
            "broken_items": self.broken_count,
            "errors": self.errors_count,
            "success_rate": success_rate,
            "items_per_hour": items_per_hour,
            "break_cycles": self.break_attempts,
            "empty_crafts": self.consecutive_empty_crafts,
        }

    def run(self):
        self.running = True
        self.log("🚀 Ядро бота запущено", "SUCCESS")

        try:
            while self.running:
                if self.paused:
                    time.sleep(0.5)
                    continue

                need_break = False
                break_reason = ""

                if self.auto_break and self.crafted_count >= self.break_count:
                    need_break = True
                    break_reason = f"достигнут лимит ({self.crafted_count}/{self.break_count} предметов)"

                elif self.consecutive_empty_crafts >= self.empty_craft_threshold:
                    need_break = True
                    break_reason = f"кончились ресурсы ({self.consecutive_empty_crafts} пустых крафтов подряд)"

                if need_break:
                    self.log(f"⚡ Запускаем разбор: {break_reason}", "INFO")

                    keyboard.press_and_release("esc")
                    time.sleep(1.0)

                    self.log("Поворачиваем к дробилке...", "INFO")
                    self.turn_character("right")
                    time.sleep(1.0)

                    self.log("Запускаем процедуру разбора...", "INFO")
                    self.start_break_items()

                    while self.break_in_progress and self.running:
                        time.sleep(0.5)

                    self.log("Поворачиваем обратно к крафту...", "INFO")
                    self.turn_character("left")
                    time.sleep(1.0)

                    self.crafted_count = 0
                    self.consecutive_empty_crafts = 0
                    self.update_gui()

                    if not self.open_craft_interface():
                        self.log("Не удалось открыть интерфейс крафта, пропускаем цикл", "WARNING")
                        time.sleep(2.0)
                        continue

                    self.log("✅ Разбор завершен, продолжаем крафт", "SUCCESS")
                    time.sleep(1.0)

                success = self.craft_cycle()

                if success:
                    self.log("Пауза 2 секунды перед следующим циклом...", "INFO")
                    time.sleep(2)
                else:
                    self.log("Пауза 1 секунда перед повторной попыткой...", "INFO")
                    time.sleep(1)

        except KeyboardInterrupt:
            self.log("Бот остановлен пользователем", "INFO")
        except Exception as e:
            self.log(f"Критическая ошибка в основном цикле: {str(e)}", "ERROR")
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self.log("🛑 Ядро бота остановлено", "INFO")

    def stop(self):
        self.running = False
        self.log("Получена команда остановки...", "INFO")

    def pause(self):
        self.paused = True
        self.log("Бот приостановлен", "INFO")

    def resume(self):
        self.paused = False
        self.log("Бот возобновлен", "INFO")
