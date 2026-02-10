import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import os
import json
import sys
from typing import Dict, Any
class RegionSelectorOverlay:
    """
    Оверлей для выделения области мышью.
    Возвращает (x, y, w, h) в координатах экрана или None если отмена.
    """

    def __init__(self, parent, title="Выделение области"):
        self.parent = parent
        self.title = title

        self.result = None
        self.start_x = None
        self.start_y = None
        self.rect_id = None

        # Создаём поверх всего экрана
        self.win = tk.Toplevel(parent)
        self.win.title(self.title)
        self.win.attributes("-topmost", True)
        self.win.attributes("-fullscreen", True)
        self.win.attributes("-alpha", 0.25)  # прозрачность фона
        self.win.configure(bg="black")
        self.win.overrideredirect(True)

        # Холст на весь экран (для рисования прямоугольника)
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)

        # Подсказка
        self.hint = self.canvas.create_text(
            20, 20,
            text="Зажми ЛКМ и выдели область. Enter — подтвердить, Esc — отмена",
            anchor="nw",
            fill="white",
            font=("Arial", 14, "bold")
        )

        # События мыши
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # Клавиши
        self.win.bind("<Escape>", self.cancel)
        self.win.bind("<Return>", self.confirm)

    def on_press(self, event):
        self.start_x = self.win.winfo_pointerx()
        self.start_y = self.win.winfo_pointery()

        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

        # Рисуем начальный прямоугольник
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=3
        )

    def on_drag(self, event):
        if self.rect_id is None:
            return

        cur_x = self.win.winfo_pointerx()
        cur_y = self.win.winfo_pointery()

        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

        # Обновляем подсказку с размерами
        x1, y1, x2, y2 = self._normalized_coords(self.start_x, self.start_y, cur_x, cur_y)
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        self.canvas.itemconfig(self.hint, text=f"Выделение: x={x1}, y={y1}, w={w}, h={h} | Enter — ок, Esc — отмена")

    def on_release(self, event):
        # Ничего критичного — результат подтвердим Enter
        pass

    def _normalized_coords(self, x1, y1, x2, y2):
        left = min(int(x1), int(x2))
        top = min(int(y1), int(y2))
        right = max(int(x1), int(x2))
        bottom = max(int(y1), int(y2))
        return left, top, right, bottom

    def confirm(self, event=None):
        if self.rect_id is None:
            self.result = None
            self._close()
            return

        x1, y1, x2, y2 = self.canvas.coords(self.rect_id)
        left, top, right, bottom = self._normalized_coords(x1, y1, x2, y2)
        w = right - left
        h = bottom - top

        # Минимальная защита от "клика без выделения"
        if w < 5 or h < 5:
            self.result = None
        else:
            self.result = (left, top, w, h)

        self._close()

    def cancel(self, event=None):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.win.grab_release()
        except:
            pass
        self.win.destroy()

    def show(self):
        # Блокируем ввод в основное окно до выбора
        self.win.grab_set()
        self.parent.wait_window(self.win)
        return self.result

class CraftBotGUI:
    def __init__(self, license_client=None):
        self.bot_running = False
        self.bot_paused = False
        self.bot_thread = None
        self.bot_core = None
        
        # Лицензирование
        self.license_client = license_client
        self.license_check_interval = 300  # 5 минут
        self.license_check_thread = None
        self.license_valid = True
        
        # Инициализируем переменные
        self.region = None
        self.inventory_region = None
        self.items = {}
        self.create_button_path = ""
        self.no_resources_path = ""  # НОВОЕ: путь к изображению "нет ресурсов"
        
        # Статистика
        self.start_time = None
        self.statistics = {
            "cycles": 0,
            "crafted": 0,
            "broken": 0,
            "errors": 0
        }
        
        self.create_gui()
        self.load_config()
        
        # Запускаем проверку лицензии
        if self.license_client:
            self.start_license_check()
    
    def log_message(self, message: str, level: str = "INFO"):
        """Добавление сообщения в лог"""
        timestamp = time.strftime("%H:%M:%S")
        level_icon = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "DEBUG": "🔍"
        }.get(level, "ℹ️")
        
        formatted_message = f"[{timestamp}] {level_icon} {message}"
        
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, formatted_message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        
        print(formatted_message)
    
    def create_gui(self):
        """Создание графического интерфейса"""
        self.root = tk.Tk()
        
        # Добавляем информацию о лицензии в заголовок
        license_status = "✅ Лицензия активна"
        if self.license_client and self.license_client.expiry_date:
            try:
                from datetime import datetime
                expiry = datetime.fromisoformat(self.license_client.expiry_date.replace('Z', '+00:00'))
                expiry_str = expiry.strftime("%d.%m.%Y %H:%M")
                license_status = f"✅ Лицензия до: {expiry_str}"
            except:
                pass
        
        self.root.title(f"Крафтер Бот + Дробилка v7.2 - {license_status}")
        self.root.geometry("1000x1000")
        
        # Обработка закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Заголовок с информацией о лицензии
        title_label = ttk.Label(main_frame, text="КРАФТЕР БОТ + ДРОБИЛКА v7.2", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 5))
        
        # Строка с информацией о лицензии
        license_info = ""
        if self.license_client:
            if self.license_client.expiry_date:
                try:
                    from datetime import datetime
                    expiry = datetime.fromisoformat(self.license_client.expiry_date.replace('Z', '+00:00'))
                    license_info = f"Лицензия действительна до: {expiry.strftime('%d.%m.%Y %H:%M')}"
                except:
                    license_info = "✅ Лицензия активна"
            else:
                license_info = "✅ Лицензия активна"
        
        subtitle_label = ttk.Label(main_frame, 
                                   text=f"Система лицензирования | {license_info}", 
                                   font=("Arial", 10), 
                                   foreground="green" if self.license_client else "red")
        subtitle_label.grid(row=1, column=0, columnspan=3, pady=(0, 10))
        
        # Фрейм управления
        control_frame = ttk.LabelFrame(main_frame, text="Управление", padding="10")
        control_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10), columnspan=3)
        
        btn_frame = ttk.Frame(control_frame)
        btn_frame.grid(row=0, column=0, columnspan=4)
        
        self.start_btn = ttk.Button(btn_frame, text="▶ Старт бота", 
                                   command=self.start_bot, width=15, style="Accent.TButton")
        self.start_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_btn = ttk.Button(btn_frame, text="⏹ Стоп бота", 
                                  command=self.stop_bot, width=15, state='disabled')
        self.stop_btn.grid(row=0, column=1, padx=(0, 10))
        
        self.pause_btn = ttk.Button(btn_frame, text="⏸ Пауза", 
                                   command=self.pause_bot, width=15, state='disabled')
        self.pause_btn.grid(row=0, column=2, padx=(0, 10))
        
        ttk.Button(btn_frame, text="▶ Тест мыши", 
                  command=self.test_mouse_move, width=15).grid(row=0, column=3, padx=(0, 10))
        
        ttk.Label(control_frame, text="Горячая клавиша: Home - вкл/выкл, Pause - пауза").grid(row=1, column=0, pady=(10, 0), columnspan=4)
        
        # Конфигурация крафта
        craft_config_frame = ttk.LabelFrame(main_frame, text="Конфигурация крафта", padding="10")
        craft_config_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10), columnspan=3)
        
        # Кнопка создания
        create_frame = ttk.Frame(craft_config_frame)
        create_frame.grid(row=0, column=0, sticky=tk.W, pady=(0, 10), columnspan=2)
        
        ttk.Button(create_frame, text="📁 Загрузить кнопку 'Создать'", 
                  command=self.load_create_button, width=25).grid(row=0, column=0)
        
        self.create_button_label = ttk.Label(create_frame, text="Не загружено", foreground="gray")
        self.create_button_label.grid(row=0, column=1, padx=(10, 0))
        
        # Изображение "нет ресурсов" - НОВОЕ
        resources_frame = ttk.Frame(craft_config_frame)
        resources_frame.grid(row=1, column=0, sticky=tk.W, pady=(0, 10), columnspan=2)
        
        ttk.Button(resources_frame, text="🔄 Загрузить 'нет ресурсов'", 
                  command=self.load_no_resources_image, width=25).grid(row=0, column=0)
        
        self.no_resources_label = ttk.Label(resources_frame, text="Не загружено", foreground="gray")
        self.no_resources_label.grid(row=0, column=1, padx=(10, 0))
        
        # Область предметов для крафта
        region_frame = ttk.Frame(craft_config_frame)
        region_frame.grid(row=2, column=0, sticky=tk.W, pady=(0, 10), columnspan=2)
        
        ttk.Button(region_frame, text="📐 Выделить область предметов", 
                  command=lambda: self.select_region(is_inventory=False), width=25).grid(row=0, column=0)
        
        self.region_label = ttk.Label(region_frame, text="Не выделена", foreground="gray")
        self.region_label.grid(row=0, column=1, padx=(10, 0))
        
        # Область инвентаря для разбора
        inv_frame = ttk.Frame(craft_config_frame)
        inv_frame.grid(row=3, column=0, sticky=tk.W, pady=(0, 10), columnspan=2)
        
        ttk.Button(inv_frame, text="🎒 Выделить область инвентаря", 
                  command=lambda: self.select_region(is_inventory=True), width=25).grid(row=0, column=0)
        
        self.inv_region_label = ttk.Label(inv_frame, text="Не выделена", foreground="gray")
        self.inv_region_label.grid(row=0, column=1, padx=(10, 0))
        
        # Настройки крафта
        settings_frame = ttk.LabelFrame(craft_config_frame, text="Настройки крафта", padding="10")
        settings_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(settings_frame, text="Задержка после создания (сек):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.create_delay_var = tk.StringVar(value="2.0")
        ttk.Entry(settings_frame, textvariable=self.create_delay_var, width=8).grid(row=0, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        ttk.Label(settings_frame, text="Задержка между кликами (сек):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.click_delay_var = tk.StringVar(value="0.3")
        ttk.Entry(settings_frame, textvariable=self.click_delay_var, width=8).grid(row=1, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        ttk.Label(settings_frame, text="Порог совпадения (%):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.threshold_var = tk.StringVar(value="75")
        ttk.Entry(settings_frame, textvariable=self.threshold_var, width=8).grid(row=2, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        ttk.Label(settings_frame, text="Пустых крафтов до разбора:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.empty_crafts_var = tk.StringVar(value="3")
        ttk.Entry(settings_frame, textvariable=self.empty_crafts_var, width=8).grid(row=3, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        # Конфигурация дробилки
        break_config_frame = ttk.LabelFrame(main_frame, text="Конфигурация дробилки", padding="10")
        break_config_frame.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=(0, 10), columnspan=3)
        
        ttk.Label(break_config_frame, text="Предметов до разбора:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.break_count_var = tk.StringVar(value="10")
        ttk.Entry(break_config_frame, textvariable=self.break_count_var, width=10).grid(row=0, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        ttk.Label(break_config_frame, text="Пикселей для поворота:").grid(row=0, column=2, sticky=tk.W, pady=5)
        self.turn_pixels_var = tk.StringVar(value="500")
        ttk.Entry(break_config_frame, textvariable=self.turn_pixels_var, width=8).grid(row=0, column=3, pady=5, padx=(10, 20), sticky=tk.W)
        
        ttk.Label(break_config_frame, text="Задержка поворота (сек):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.turn_delay_var = tk.StringVar(value="1.0")
        ttk.Entry(break_config_frame, textvariable=self.turn_delay_var, width=8).grid(row=1, column=1, pady=5, padx=(10, 20), sticky=tk.W)
        
        self.auto_break_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(break_config_frame, text="Автоматический разбор", 
                       variable=self.auto_break_var).grid(row=1, column=2, pady=5, padx=(10, 0), sticky=tk.W, columnspan=2)
        
        # Предметы для крафта
        items_frame = ttk.LabelFrame(main_frame, text="Предметы для крафта и разбора", padding="10")
        items_frame.grid(row=6, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10), columnspan=3)
        
        item_controls = ttk.Frame(items_frame)
        item_controls.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Button(item_controls, text="➕ Добавить предмет", 
                  command=self.add_item_dialog, width=18).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(item_controls, text="✏️ Редактировать", 
                  command=self.edit_item_dialog, width=15).grid(row=0, column=1, padx=5)
        ttk.Button(item_controls, text="🗑️ Удалить", 
                  command=self.delete_item, width=12).grid(row=0, column=2, padx=5)
        ttk.Button(item_controls, text="💾 Сохранить", 
                  command=self.save_config, width=12).grid(row=0, column=3, padx=5)
        ttk.Button(item_controls, text="📂 Загрузить", 
                  command=self.load_config, width=12).grid(row=0, column=4, padx=(5, 0))
        
        # Список предметов
        tree_frame = ttk.Frame(items_frame)
        tree_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        items_frame.rowconfigure(1, weight=1)
        items_frame.columnconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.items_tree = ttk.Treeview(tree_frame, 
                                      columns=("Грейды", "Разбирать", "Статус"), 
                                      show="tree headings", 
                                      height=8,
                                      yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.items_tree.yview)
        
        self.items_tree.heading("#0", text="Предмет")
        self.items_tree.heading("Грейды", text="Грейдов")
        self.items_tree.heading("Разбирать", text="Разбирать")
        self.items_tree.heading("Статус", text="Статус")
        
        self.items_tree.column("#0", width=150, minwidth=150)
        self.items_tree.column("Грейды", width=80, minwidth=80)
        self.items_tree.column("Разбирать", width=80, minwidth=80)
        self.items_tree.column("Статус", width=100, minwidth=100)
        
        self.items_tree.pack(fill=tk.BOTH, expand=True)
        
        # Статус и статистика
        status_frame = ttk.LabelFrame(main_frame, text="Статус работы и статистика", padding="10")
        status_frame.grid(row=7, column=0, sticky=(tk.W, tk.E), pady=(0, 10), columnspan=3)
        
        self.status_label = ttk.Label(status_frame, text="🟡 Бот остановлен", font=("Arial", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        # Информация о лицензии
        if self.license_client and self.license_client.license_key:
            license_key_short = self.license_client.license_key[:8] + "..." + self.license_client.license_key[-4:]
            self.license_info_label = ttk.Label(status_frame, 
                                               text=f"🔑 Лицензия: {license_key_short}", 
                                               font=("Arial", 9),
                                               foreground="green")
            self.license_info_label.grid(row=0, column=1, sticky=tk.E)
        
        # Счетчики в реальном времени
        counters_frame = ttk.Frame(status_frame)
        counters_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 5), columnspan=2)
        
        self.crafted_label = ttk.Label(counters_frame, text="Создано: 0")
        self.crafted_label.grid(row=0, column=0, padx=(0, 20))
        
        self.broken_label = ttk.Label(counters_frame, text="Разобрано: 0")
        self.broken_label.grid(row=0, column=1, padx=(0, 20))
        
        self.cycles_label = ttk.Label(counters_frame, text="Циклов: 0")
        self.cycles_label.grid(row=0, column=2)
        
        # Дополнительная статистика
        stats_frame = ttk.Frame(status_frame)
        stats_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(5, 5), columnspan=2)
        
        self.errors_label = ttk.Label(stats_frame, text="Ошибок: 0")
        self.errors_label.grid(row=0, column=0, padx=(0, 20))
        
        self.time_label = ttk.Label(stats_frame, text="Время: 00:00:00")
        self.time_label.grid(row=0, column=1, padx=(0, 20))
        
        self.rate_label = ttk.Label(stats_frame, text="Пред/час: 0")
        self.rate_label.grid(row=0, column=2)
        
        # Логи
        log_frame = ttk.Frame(status_frame)
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(10, 0), columnspan=2)
        
        ttk.Label(log_frame, text="Логи работы:", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=tk.W)
        
        self.log_text = tk.Text(log_frame, height=6, width=110, wrap=tk.WORD, font=("Courier", 9))
        self.log_text.grid(row=1, column=0, pady=(5, 0))
        self.log_text.config(state='disabled')
        
        log_scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        
        # Кнопка очистки логов
        ttk.Button(log_frame, text="🧹 Очистить логи", 
                  command=self.clear_logs, width=12).grid(row=0, column=1, sticky=tk.E)
        
        style.configure("Accent.TButton", foreground="white", background="#0078D7")
        style.configure("Pause.TButton", foreground="white", background="#FF9800")
        
        for i in range(3):
            main_frame.columnconfigure(i, weight=1)
        
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        self.log_message("✅ Интерфейс загружен", "INFO")
        self.log_message("✅ Используем WinAPI SendInput для управления мышью", "INFO")
        if self.license_client:
            self.log_message(f"✅ Лицензия активна. HWID: {self.license_client.hardware_id}", "INFO")
        else:
            self.log_message("⚠️ Система лицензирования не инициализирована", "WARNING")
        self.log_message("⚠️ Бот теперь проверяет наличие ресурсов перед крафтом!", "INFO")
    
    def start_license_check(self):
        """Запуск фоновой проверки лицензии"""
        if not self.license_client:
            return
        
        def check_license():
            while self.bot_running:
                time.sleep(self.license_check_interval)
                
                try:
                    if self.license_client and self.license_client.license_key:
                        result = self.license_client.validate_license()
                        
                        if not result.get('valid'):
                            self.license_valid = False
                            
                            # Показываем сообщение об ошибке
                            self.root.after(0, self.show_license_error, 
                                          result.get('message', 'Лицензия недействительна'))
                            
                            # Останавливаем бота
                            self.stop_bot()
                except:
                    pass
        
        self.license_check_thread = threading.Thread(target=check_license, daemon=True)
        self.license_check_thread.start()
    
    def show_license_error(self, message):
        """Показать ошибку лицензии"""
        messagebox.showerror(
            "Ошибка лицензии",
            f"Лицензия стала недействительной!\n\n"
            f"Причина: {message}\n\n"
            f"Бот будет остановлен. Перезапустите приложение для повторной активации."
        )
        
        # Обновляем заголовок окна
        self.root.title("Крафтер Бот + Дробилка v7.2 - ❌ Лицензия недействительна")
        
        # Показываем сообщение в интерфейсе
        if hasattr(self, 'status_frame'):
            self.license_status_label = ttk.Label(
                self.status_frame,
                text="❌ Лицензия недействительна! Перезапустите приложение.",
                font=("Arial", 10, "bold"),
                foreground="red"
            )
            self.license_status_label.grid(row=4, column=0, columnspan=4, pady=(10, 5))
    
    def load_create_button(self):
        """Загрузка изображения кнопки 'Создать'"""
        try:
            file_path = filedialog.askopenfilename(
                title="Выберите изображение кнопки 'Создать'",
                filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg"), ("All files", "*.*")]
            )
            
            if file_path:
                if os.path.exists(file_path):
                    self.create_button_path = os.path.abspath(file_path)
                    filename = os.path.basename(file_path)
                    display_name = filename[:25] + ("..." if len(filename) > 25 else "")
                    self.create_button_label.config(text=display_name)
                    self.log_message(f"Загружена кнопка создания: {filename}", "SUCCESS")
                else:
                    messagebox.showerror("Ошибка", "Выбранный файл не существует!")
        except Exception as e:
            self.log_message(f"Ошибка при загрузке кнопки: {str(e)}", "ERROR")
    
    def load_no_resources_image(self):
        """Загрузка изображения для проверки 'нет ресурсов'"""
        try:
            file_path = filedialog.askopenfilename(
                title="Выберите изображение признака 'нет ресурсов' (серая кнопка или текст)",
                filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg"), ("All files", "*.*")]
            )
            
            if file_path:
                if os.path.exists(file_path):
                    self.no_resources_path = os.path.abspath(file_path)
                    filename = os.path.basename(file_path)
                    display_name = filename[:25] + ("..." if len(filename) > 25 else "")
                    self.no_resources_label.config(text=display_name)
                    self.log_message(f"Загружено изображение проверки ресурсов: {filename}", "SUCCESS")
                else:
                    messagebox.showerror("Ошибка", "Выбранный файл не существует!")
        except Exception as e:
            self.log_message(f"Ошибка при загрузке изображения: {str(e)}", "ERROR")
    
    def select_region(self, is_inventory=False):
        """Выделение области мышью через оверлей"""
        try:
            # Свернём окно, чтобы не мешало выделять
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.2)

            title = "Выделите область ИНВЕНТАРЯ" if is_inventory else "Выделите область ПРЕДМЕТОВ"
            overlay = RegionSelectorOverlay(self.root, title=title)
            region = overlay.show()

            # Возвращаем окно назад
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

            if not region:
                self.log_message("Выделение области отменено", "WARNING")
                return

            x, y, w, h = region

            if is_inventory:
                self.inventory_region = (x, y, w, h)
                self.inv_region_label.config(text=f"{w}x{h} пикселей")
                self.log_message(f"✅ Область инвентаря: x={x}, y={y}, w={w}, h={h}", "SUCCESS")
            else:
                self.region = (x, y, w, h)
                self.region_label.config(text=f"{w}x{h} пикселей")
                self.log_message(f"✅ Область предметов: x={x}, y={y}, w={w}, h={h}", "SUCCESS")

        except Exception as e:
            try:
                self.root.deiconify()
            except:
                pass
            self.log_message(f"Ошибка выделения области: {str(e)}", "ERROR")
            messagebox.showerror("Ошибка", f"Не удалось выделить область:\n{str(e)}")
        
    
    def update_counters(self, crafted=0, broken=0, cycles=0):
        """Обновление счетчиков"""
        if crafted >= 0:
            self.crafted_label.config(text=f"Создано: {crafted}")
            self.statistics["crafted"] = crafted
        
        if broken >= 0:
            self.broken_label.config(text=f"Разобрано: {broken}")
            self.statistics["broken"] = broken
        
        if cycles >= 0:
            self.cycles_label.config(text=f"Циклов: {cycles}")
            self.statistics["cycles"] = cycles
        
        # Обновляем время работы
        if self.start_time:
            elapsed = time.time() - self.start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.time_label.config(text=f"Время: {hours:02d}:{minutes:02d}:{seconds:02d}")
            
            # Обновляем скорость
            if elapsed > 0:
                items_per_hour = self.statistics["crafted"] / elapsed * 3600
                self.rate_label.config(text=f"Пред/час: {items_per_hour:.1f}")
    
    def test_mouse_move(self):
        """Тестирование перемещения мыши в центр"""
        self.log_message("Тестируем перемещение мыши через WinAPI...", "INFO")
        
        try:
            from bot_core import WinAPIMouseController
            mouse = WinAPIMouseController()
            screen_width, screen_height = mouse.get_screen_size()
            center_x = screen_width // 2
            center_y = screen_height // 2
            
            # Перемещаем мышь в центр
            mouse.move_mouse_to(center_x, center_y, duration=0.5)
            
            self.log_message(f"Мышь перемещена в центр через WinAPI: ({center_x}, {center_y})", "SUCCESS")
            
            # Возвращаем обратно
            time.sleep(1)
            original_x, original_y = mouse.get_position()
            mouse.move_mouse_to(original_x, original_y, duration=0.5)
            
        except Exception as e:
            self.log_message(f"Ошибка теста мыши через WinAPI: {str(e)}", "ERROR")
            self.log_message("Пробуем через pyautogui...", "INFO")
            
            try:
                import pyautogui
                screen_width, screen_height = pyautogui.size()
                center_x = screen_width // 2
                center_y = screen_height // 2
                
                pyautogui.moveTo(center_x, center_y, duration=0.5)
                
                self.log_message(f"Мышь перемещена в центр через pyautogui: ({center_x}, {center_y})", "SUCCESS")
            except Exception as e2:
                self.log_message(f"Ошибка теста мыши через pyautogui: {str(e2)}", "ERROR")
    
    def start_bot(self):
        """Запуск бота"""
        try:
            # Проверяем лицензию перед запуском
            if self.license_client:
                if not self.license_client.is_license_active():
                    messagebox.showerror(
                        "Ошибка лицензии",
                        "Лицензия недействительна или истекла.\n"
                        "Перезапустите приложение для активации."
                    )
                    return
            else:
                messagebox.showerror(
                    "Ошибка лицензии",
                    "Система лицензирования не инициализирована.\n"
                    "Запустите приложение через main.py."
                )
                return
            
            # Проверка обязательных параметров
            if not self.create_button_path:
                messagebox.showerror("Ошибка", "Сначала загрузите изображение кнопки 'Создать'")
                return
            
            if not os.path.exists(self.create_button_path):
                messagebox.showerror("Ошибка", f"Файл кнопки 'Создать' не найден:\n{self.create_button_path}")
                return
            
            if not self.region:
                messagebox.showerror("Ошибка", "Сначала выделите область для предметов")
                return
            
            if not self.items:
                messagebox.showerror("Ошибка", "Добавьте хотя бы один предмет для крафта")
                return
            
            # Проверка файлов изображений
            missing_files = []
            for item_name, item_data in self.items.items():
                for grade in item_data.get('grades', []):
                    path = grade.get('path', '')
                    if path and not os.path.exists(path):
                        missing_files.append(f"{item_name}: {os.path.basename(path)}")
            
            if missing_files:
                messagebox.showerror("Ошибка", 
                    f"Не найдены файлы изображений:\n" + "\n".join(missing_files[:5]) + 
                    ("\n..." if len(missing_files) > 5 else ""))
                return
            
            # Проверка числовых параметров
            try:
                break_count = int(self.break_count_var.get())
                if break_count <= 0:
                    messagebox.showerror("Ошибка", "Количество предметов до разбора должно быть больше 0")
                    return
                
                turn_pixels = int(self.turn_pixels_var.get())
                if turn_pixels <= 0:
                    messagebox.showerror("Ошибка", "Количество пикселей для поворота должно быть больше 0")
                    return
                
                empty_crafts = int(self.empty_crafts_var.get())
                if empty_crafts <= 0:
                    messagebox.showerror("Ошибка", "Количество пустых крафтов до разбора должно быть больше 0")
                    return
                    
            except ValueError:
                messagebox.showerror("Ошибка", "Введите числа для настроек разбора, поворота и пустых крафтов")
                return
            
            # Импортируем и создаем бота
            from bot_core import CraftBotCore
            
            self.bot_core = CraftBotCore(
                create_button_path=self.create_button_path,
                region=self.region,
                items=self.items,
                create_delay=float(self.create_delay_var.get()),
                click_delay=float(self.click_delay_var.get()),
                threshold=float(self.threshold_var.get()) / 100,
                break_count=int(self.break_count_var.get()),
                turn_delay=float(self.turn_delay_var.get()),
                turn_pixels=int(self.turn_pixels_var.get()),
                inventory_region=self.inventory_region,
                auto_break=self.auto_break_var.get(),
                no_resources_path=self.no_resources_path if hasattr(self, 'no_resources_path') and self.no_resources_path else None,
                gui_callback=self.update_counters,
                log_callback=self.log_message
            )
            
            # Устанавливаем кастомный порог для пустых крафтов
            if hasattr(self.bot_core, 'empty_craft_threshold'):
                self.bot_core.empty_craft_threshold = int(self.empty_crafts_var.get())
            
            # Сброс счетчиков
            self.start_time = time.time()
            self.statistics = {"cycles": 0, "crafted": 0, "broken": 0, "errors": 0}
            self.update_counters(0, 0, 0)
            
            # Запуск бота в отдельном потоке
            self.bot_running = True
            self.bot_paused = False
            self.bot_thread = threading.Thread(target=self.run_bot, daemon=True)
            self.bot_thread.start()
            
            # Обновление интерфейса
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
            self.pause_btn.config(state='normal')
            self.status_label.config(text="🟢 Бот запущен")
            self.log_message("🚀 БОТ ЗАПУЩЕН с интеллектуальной проверкой ресурсов", "SUCCESS")
            self.log_message(f"Лицензия активна. HWID: {self.license_client.hardware_id}", "INFO")
            self.log_message(f"Используем WinAPI SendInput для управления мышью", "INFO")
            self.log_message(f"Поворот настроен на {self.turn_pixels_var.get()} пикселей", "INFO")
            self.log_message(f"Разбор при {self.empty_crafts_var.get()} пустых крафтах подряд", "INFO")
            self.log_message("✅ Бот теперь проверяет ресурсы перед крафтом!", "INFO")
            
            # Настройка горячих клавиш
            self.setup_hotkeys()
            
        except Exception as e:
            self.log_message(f"Ошибка при запуске бота: {str(e)}", "ERROR")
            import traceback
            self.log_message(traceback.format_exc(), "ERROR")
            messagebox.showerror("Ошибка", f"Не удалось запустить бота:\n{str(e)}")
    
    def run_bot(self):
        """Запуск цикла бота в отдельном потоке"""
        try:
            self.bot_core.run()
        except Exception as e:
            self.log_message(f"Критическая ошибка в боте: {str(e)}", "ERROR")
            import traceback
            self.log_message(traceback.format_exc(), "ERROR")
        finally:
            self.stop_bot()
    
    def stop_bot(self):
        """Остановка бота"""
        try:
            if self.bot_core:
                self.bot_core.stop()
            
            self.bot_running = False
            self.bot_paused = False
            
            # Обновление интерфейса
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
            self.pause_btn.config(state='disabled')
            self.status_label.config(text="🟡 Бот остановлен")
            
            self.log_message("🛑 БОТ ОСТАНОВЛЕН", "INFO")
            
            # Удаление горячих клавиш
            self.remove_hotkeys()
            
        except Exception as e:
            self.log_message(f"Ошибка при остановке бота: {str(e)}", "ERROR")
    
    def pause_bot(self):
        """Приостановка/возобновление работы бота"""
        if not self.bot_core:
            return
        
        if not self.bot_paused:
            self.bot_core.pause()
            self.bot_paused = True
            self.pause_btn.config(text="▶ Возобновить")
            self.status_label.config(text="⏸ Бот приостановлен")
            self.log_message("Бот приостановлен", "INFO")
        else:
            self.bot_core.resume()
            self.bot_paused = False
            self.pause_btn.config(text="⏸ Пауза")
            self.status_label.config(text="🟢 Бот запущен")
            self.log_message("Бот возобновлен", "INFO")
    
    def setup_hotkeys(self):
        """Настройка горячих клавиш"""
        try:
            import keyboard
            
            # Удаляем старые хоткеи
            keyboard.unhook_all()
            
            # Настраиваем новые
            keyboard.add_hotkey('home', self.toggle_bot)
            keyboard.add_hotkey('pause', self.toggle_pause)
            
            self.log_message("Горячие клавиши настроены: Home - вкл/выкл, Pause - пауза", "INFO")
        except Exception as e:
            self.log_message(f"Не удалось настроить горячие клавиши: {str(e)}", "WARNING")
    
    def remove_hotkeys(self):
        """Удаление горячих клавиш"""
        try:
            import keyboard
            keyboard.unhook_all()
        except:
            pass
    
    def toggle_bot(self):
        """Переключение состояния бота (горячая клавиша)"""
        if self.bot_running:
            self.stop_bot()
        else:
            self.start_bot()
    
    def toggle_pause(self):
        """Переключение паузы (горячая клавиша)"""
        if self.bot_running:
            self.pause_bot()
    
    def add_item_dialog(self):
        """Диалог добавления нового предмета"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить предмет")
        dialog.geometry("550x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Название предмета:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        name_entry = ttk.Entry(dialog, width=30)
        name_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        grades = ["Зеленый", "Синий", "Фиолетовый", "Желтый"]
        grade_data = []
        grade_labels = []
        break_vars = []
        
        def load_grade_image(grade_index):
            file_path = filedialog.askopenfilename(
                title=f"Изображение для {grades[grade_index]} грейда",
                filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg"), ("All files", "*.*")]
            )
            if file_path and os.path.exists(file_path):
                grade_data[grade_index]['path'] = os.path.abspath(file_path)
                filename = os.path.basename(file_path)
                grade_labels[grade_index].config(text=filename[:20] + ("..." if len(filename) > 20 else ""))
            elif file_path:
                messagebox.showerror("Ошибка", "Выбранный файл не существует!")
        
        for i in range(len(grades)):
            grade_data.append({'path': '', 'break': False})
        
        for i, grade in enumerate(grades):
            row = i + 1
            
            ttk.Label(dialog, text=f"{grade}:").grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
            
            grade_label = ttk.Label(dialog, text="Не загружено", foreground="gray")
            grade_label.grid(row=row, column=1, padx=10, pady=5, sticky=tk.W)
            grade_labels.append(grade_label)
            
            ttk.Button(dialog, text="Загрузить", 
                      command=lambda idx=i: load_grade_image(idx), width=10).grid(row=row, column=2, padx=10, pady=5)
            
            break_var = tk.BooleanVar(value=False)
            break_vars.append(break_var)
            ttk.Checkbutton(dialog, text="Разбирать", variable=break_var).grid(row=row, column=3, padx=10, pady=5)
        
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=len(grades)+2, column=0, columnspan=4, pady=20)
        
        def save_item():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Ошибка", "Введите название предмета")
                return
            
            loaded_grades = [g for g in grade_data if g['path']]
            if not loaded_grades:
                messagebox.showerror("Ошибка", "Загрузите хотя бы один грейд")
                return
            
            for i, break_var in enumerate(break_vars):
                if i < len(grade_data) and grade_data[i]['path']:
                    grade_data[i]['break'] = break_var.get()
            
            valid_grades = [g for g in grade_data if g['path']]
            
            for grade in valid_grades:
                if not os.path.exists(grade['path']):
                    messagebox.showerror("Ошибка", f"Файл не найден:\n{grade['path']}")
                    return
            
            self.items[name] = {
                'grades': valid_grades,
                'count': 0
            }
            
            loaded_count = len(valid_grades)
            break_count = len([g for g in valid_grades if g.get('break', False)])
            status = "✅ Готов" if loaded_count > 0 else "⚠️ Нет грейдов"
            self.items_tree.insert('', 'end', text=name, 
                                  values=(f"{loaded_count}", f"{break_count}", status))
            
            dialog.destroy()
            self.log_message(f"Добавлен предмет: '{name}' ({loaded_count} грейдов, {break_count} на разбор)", "SUCCESS")
        
        ttk.Button(button_frame, text="💾 Сохранить", command=save_item, width=15).grid(row=0, column=0, padx=5)
        ttk.Button(button_frame, text="❌ Отмена", command=dialog.destroy, width=15).grid(row=0, column=1, padx=5)
    
    def edit_item_dialog(self):
        """Редактирование предмета"""
        selected = self.items_tree.selection()
        if not selected:
            messagebox.showwarning("Предупреждение", "Выберите предмет для редактирования")
            return
        
        item_name = self.items_tree.item(selected[0], 'text')
        
        if item_name in self.items:
            item_data = self.items[item_name]
            
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Редактирование: {item_name}")
            dialog.geometry("500x400")
            dialog.transient(self.root)
            dialog.grab_set()
            
            ttk.Label(dialog, text=f"Предмет: {item_name}", font=("Arial", 11, "bold")).grid(
                row=0, column=0, columnspan=3, padx=10, pady=10)
            
            ttk.Label(dialog, text="Грейды предмета:", font=("Arial", 10)).grid(
                row=1, column=0, columnspan=3, padx=10, pady=(0, 5), sticky=tk.W)
            
            frame = ttk.Frame(dialog)
            frame.grid(row=2, column=0, columnspan=3, padx=10, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
            
            canvas = tk.Canvas(frame, height=200)
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            break_vars = []
            
            for i, grade in enumerate(item_data.get('grades', [])):
                filename = os.path.basename(grade.get('path', 'Неизвестно'))
                ttk.Label(scrollable_frame, text=f"{i+1}. {filename[:40]}").grid(
                    row=i, column=0, sticky=tk.W, padx=5, pady=2)
                
                break_var = tk.BooleanVar(value=grade.get('break', False))
                break_vars.append(break_var)
                ttk.Checkbutton(scrollable_frame, text="Разбирать", variable=break_var).grid(
                    row=i, column=1, padx=5, pady=2)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            button_frame = ttk.Frame(dialog)
            button_frame.grid(row=3, column=0, columnspan=3, pady=20)
            
            def save_changes():
                for i, break_var in enumerate(break_vars):
                    if i < len(item_data['grades']):
                        item_data['grades'][i]['break'] = break_var.get()
                
                grades_count = len(item_data['grades'])
                break_count = len([g for g in item_data['grades'] if g.get('break', False)])
                self.items_tree.item(selected[0], values=(f"{grades_count}", f"{break_count}", "✅ Готов"))
                
                dialog.destroy()
                self.log_message(f"Предмет '{item_name}' обновлен", "SUCCESS")
                messagebox.showinfo("Успех", "Предмет успешно обновлен!")
            
            def add_new_grade():
                file_path = filedialog.askopenfilename(
                    title=f"Добавить грейд к предмету '{item_name}'",
                    filetypes=[("PNG files", "*.png"), ("JPEG files", "*.jpg;*.jpeg"), ("All files", "*.*")]
                )
                
                if file_path and os.path.exists(file_path):
                    break_it = messagebox.askyesno("Настройка", "Разбирать этот грейд?")
                    
                    self.items[item_name]['grades'].append({
                        'path': os.path.abspath(file_path),
                        'break': break_it
                    })
                    
                    dialog.destroy()
                    self.edit_item_dialog()
                    self.log_message(f"Добавлен новый грейд к предмету '{item_name}'", "SUCCESS")
            
            ttk.Button(button_frame, text="💾 Сохранить", command=save_changes, width=15).grid(row=0, column=0, padx=5)
            ttk.Button(button_frame, text="➕ Добавить грейд", command=add_new_grade, width=15).grid(row=0, column=1, padx=5)
            ttk.Button(button_frame, text="❌ Отмена", command=dialog.destroy, width=15).grid(row=0, column=2, padx=5)
        
        else:
            messagebox.showerror("Ошибка", "Предмет не найден!")
    
    def delete_item(self):
        """Удаление выбранного предмета"""
        selected = self.items_tree.selection()
        if not selected:
            messagebox.showwarning("Предупреждение", "Выберите предмет для удаления")
            return
        
        item_name = self.items_tree.item(selected[0], 'text')
        
        if messagebox.askyesno("Подтверждение", f"Удалить предмет '{item_name}'?"):
            if item_name in self.items:
                del self.items[item_name]
            self.items_tree.delete(selected[0])
            self.log_message(f"Удален предмет: '{item_name}'", "INFO")
    
    def clear_logs(self):
        """Очистка логов"""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state='disabled')
        self.log_message("Логи очищены", "INFO")
    
    def save_config(self):
        """Сохранение конфигурации"""
        try:
            items_to_save = {}
            for name, item_data in self.items.items():
                grades_to_save = []
                for grade in item_data.get('grades', []):
                    path = grade.get('path', '')
                    if path and os.path.exists(path):
                        grade_copy = {
                            'path': os.path.abspath(path),
                            'break': grade.get('break', False)
                        }
                        grades_to_save.append(grade_copy)
                
                if grades_to_save:
                    items_to_save[name] = {
                        'grades': grades_to_save,
                        'count': item_data.get('count', 0)
                    }
            
            config = {
                'region': self.region,
                'inventory_region': self.inventory_region,
                'create_button_path': os.path.abspath(self.create_button_path) if self.create_button_path and os.path.exists(self.create_button_path) else '',
                'no_resources_path': os.path.abspath(self.no_resources_path) if hasattr(self, 'no_resources_path') and self.no_resources_path and os.path.exists(self.no_resources_path) else '',
                'items': items_to_save,
                'create_delay': self.create_delay_var.get(),
                'click_delay': self.click_delay_var.get(),
                'threshold': self.threshold_var.get(),
                'break_count': self.break_count_var.get(),
                'turn_delay': self.turn_delay_var.get(),
                'turn_pixels': self.turn_pixels_var.get(),
                'empty_crafts': self.empty_crafts_var.get(),
                'auto_break': self.auto_break_var.get()
            }
            
            with open('craft_bot_config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            self.log_message("Конфигурация сохранена", "SUCCESS")
            messagebox.showinfo("Успех", "Конфигурация сохранена")
        except Exception as e:
            self.log_message(f"Ошибка сохранения: {str(e)}", "ERROR")
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{str(e)}")
    
    def load_config(self):
        """Загрузка конфигурации с проверкой файлов"""
        config_file = 'craft_bot_config.json'
        
        if not os.path.exists(config_file):
            self.log_message("Конфигурация не найдена, создайте новую", "INFO")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.region = None
            self.inventory_region = None
            self.items = {}
            self.no_resources_path = ""
            
            # Очистка дерева
            for item in self.items_tree.get_children():
                self.items_tree.delete(item)
            
            # Загрузка области предметов
            if 'region' in config and config['region']:
                self.region = tuple(config['region'])
                width, height = self.region[2], self.region[3]
                self.region_label.config(text=f"{width}x{height} пикселей")
                self.log_message(f"Загружена область предметов: {width}x{height}", "SUCCESS")
            
            # Загрузка области инвентаря
            if 'inventory_region' in config and config['inventory_region']:
                self.inventory_region = tuple(config['inventory_region'])
                width, height = self.inventory_region[2], self.inventory_region[3]
                self.inv_region_label.config(text=f"{width}x{height} пикселей")
                self.log_message(f"Загружена область инвентаря: {width}x{height}", "SUCCESS")
            
            # Загрузка кнопки создания
            if 'create_button_path' in config and config['create_button_path']:
                path = config['create_button_path']
                if os.path.exists(path):
                    self.create_button_path = os.path.abspath(path)
                    filename = os.path.basename(path)
                    self.create_button_label.config(text=filename[:25] + ("..." if len(filename) > 25 else ""))
                    self.log_message(f"Загружена кнопка: {filename}", "SUCCESS")
                else:
                    self.create_button_path = ""
                    self.create_button_label.config(text="⚠️ Файл не найден")
                    self.log_message(f"Файл кнопки не найден: {path}", "WARNING")
            
            # Загрузка изображения проверки ресурсов
            if 'no_resources_path' in config and config['no_resources_path']:
                path = config['no_resources_path']
                if os.path.exists(path):
                    self.no_resources_path = os.path.abspath(path)
                    filename = os.path.basename(path)
                    self.no_resources_label.config(text=filename[:25] + ("..." if len(filename) > 25 else ""))
                    self.log_message(f"Загружено изображение проверки ресурсов: {filename}", "SUCCESS")
                else:
                    self.no_resources_path = ""
                    self.no_resources_label.config(text="Не загружено")
                    self.log_message(f"Файл проверки ресурсов не найден: {path}", "WARNING")
            
            # Загрузка предметов
            if 'items' in config:
                items_loaded = 0
                items_skipped = 0
                
                for name, item_data in config['items'].items():
                    valid_grades = []
                    
                    for grade in item_data.get('grades', []):
                        path = grade.get('path', '')
                        if path and os.path.exists(path):
                            grade_copy = {
                                'path': os.path.abspath(path),
                                'break': grade.get('break', False)
                            }
                            valid_grades.append(grade_copy)
                        elif path:
                            self.log_message(f"Предмет '{name}': файл не найден - {path}", "WARNING")
                    
                    if valid_grades:
                        self.items[name] = {
                            'grades': valid_grades,
                            'count': item_data.get('count', 0)
                        }
                        
                        loaded_count = len(valid_grades)
                        break_count = len([g for g in valid_grades if g.get('break', False)])
                        self.items_tree.insert('', 'end', text=name, 
                                              values=(f"{loaded_count}", f"{break_count}", "✅ Готов"))
                        items_loaded += 1
                    else:
                        self.log_message(f"Пропущен предмет '{name}': нет валидных грейдов", "WARNING")
                        items_skipped += 1
                
                self.log_message(f"Загружено предметов: {items_loaded} (пропущено: {items_skipped})", "SUCCESS")
            
            # Загрузка настроек
            if 'create_delay' in config:
                self.create_delay_var.set(config['create_delay'])
            if 'click_delay' in config:
                self.click_delay_var.set(config['click_delay'])
            if 'threshold' in config:
                self.threshold_var.set(config['threshold'])
            if 'break_count' in config:
                self.break_count_var.set(config['break_count'])
            if 'turn_delay' in config:
                self.turn_delay_var.set(config['turn_delay'])
            if 'turn_pixels' in config:
                self.turn_pixels_var.set(config['turn_pixels'])
            if 'empty_crafts' in config:
                self.empty_crafts_var.set(config['empty_crafts'])
            if 'auto_break' in config:
                self.auto_break_var.set(config['auto_break'])
            
            self.log_message("Конфигурация загружена", "SUCCESS")
                
        except json.JSONDecodeError:
            self.log_message("Ошибка: файл конфигурации поврежден", "ERROR")
            messagebox.showerror("Ошибка", "Файл конфигурации поврежден или имеет неверный формат")
        except Exception as e:
            self.log_message(f"Ошибка загрузки: {str(e)}", "ERROR")
    
    def on_closing(self):
        """Обработка закрытия окна"""
        if self.license_client:
            self.license_client.stop_background_check()
        
        if self.bot_running:
            if messagebox.askyesno("Подтверждение", "Бот все еще работает. Остановить и выйти?"):
                self.stop_bot()
                time.sleep(1)
                self.root.destroy()
        else:
            self.root.destroy()
    
    def run(self):
        """Запуск приложения"""
        # Начальные настройки
        self.log_message("Приложение готово к работе", "SUCCESS")
        if self.license_client:
            self.log_message(f"Лицензия активна. Hardware ID: {self.license_client.hardware_id}", "INFO")
        self.log_message("Нажмите 'Тест мыши' для проверки WinAPI управления", "INFO")
        self.log_message("⚠️ Внимание: бот теперь проверяет ресурсы перед крафтом!", "INFO")
        self.log_message("📸 Совет: сделайте скриншот серой кнопки 'Создать' и загрузите как 'нет ресурсов'", "INFO")
        
        # Запуск основного цикла
        self.root.mainloop()
