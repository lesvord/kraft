import requests
import json
import os
import hashlib
import uuid
import threading
import time
import re
import logging
import platform
import psutil
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class LicenseClient:
    """Клиент для подключения к серверу лицензирования"""
    
    def __init__(self, server_url: str = "http://95.164.23.186:5000"):
        self.server_url = server_url.rstrip('/')
        self.license_key = None
        self.hardware_id = None
        self.license_valid = False
        self.expiry_date = None
        self.license_file = "license_data.json"
        self.hwid_file = "hardware_id.txt"  # Файл для постоянного хранения HWID
        self.license_check_interval = 60  # 60 секунд для минутной проверки
        self.license_check_thread = None
        self.license_check_running = False
        self.on_license_invalid_callback = None
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('license_client.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Генерируем/загружаем постоянный hardware_id
        self.hardware_id = self.get_or_create_hardware_id()
        self.logger.info(f"Инициализирован HWID: {self.hardware_id}")
    
    def get_or_create_hardware_id(self) -> str:
        """Получение или создание постоянного HWID"""
        # Пытаемся загрузить из файла
        if os.path.exists(self.hwid_file):
            try:
                with open(self.hwid_file, 'r') as f:
                    hwid = f.read().strip()
                    if hwid and hwid.startswith("CRAFT-"):
                        self.logger.info(f"Загружен сохраненный HWID: {hwid}")
                        return hwid
            except Exception as e:
                self.logger.error(f"Ошибка загрузки HWID из файла: {e}")
        
        # Генерируем новый постоянный HWID
        hwid = self.generate_stable_hardware_id()
        
        # Сохраняем в файл
        try:
            with open(self.hwid_file, 'w') as f:
                f.write(hwid)
            self.logger.info(f"Создан и сохранен новый HWID: {hwid}")
        except Exception as e:
            self.logger.error(f"Ошибка сохранения HWID: {e}")
        
        return hwid
    
    def generate_stable_hardware_id(self) -> str:
        """Генерация стабильного hardware_id на основе MAC-адреса"""
        try:
            # Получаем MAC-адрес основного сетевого интерфейса
            mac = self.get_mac_address()
            
            # Если MAC получен, создаем хэш на его основе
            if mac:
                # Удаляем разделители из MAC-адреса
                mac_clean = mac.replace(':', '').replace('-', '')
                
                # Создаем UUID на основе MAC-адреса (версия 1 использует MAC)
                stable_uuid = uuid.uuid1()
                
                # Создаем хэш на основе комбинации MAC и стабильной информации
                combined = f"{mac_clean}-{platform.node()}"
                hardware_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()
                
                return f"CRAFT-{hardware_hash}"
            else:
                # Резервный вариант: используем серийный номер диска
                return self.generate_hardware_id_backup()
                
        except Exception as e:
            self.logger.error(f"Ошибка генерации стабильного HWID: {e}")
            return f"CRAFT-{uuid.uuid4().hex[:20].upper()}"
    
    def get_mac_address(self) -> str:
        """Получение MAC-адреса основного сетевого интерфейса"""
        try:
            # Для Windows
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['getmac', '/v', '/fo', 'csv', '/nh'],
                    capture_output=True, text=True, shell=True
                )
                
                if result.stdout:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if 'Ethernet' in line or 'Wi-Fi' in line or 'Беспроводная сеть' in line:
                            parts = line.split(',')
                            if len(parts) > 2:
                                mac = parts[2].strip().replace('-', ':').replace('"', '')
                                if len(mac) == 17:  # Проверяем формат MAC
                                    return mac
            
            # Для Linux/Mac
            else:
                # Пробуем получить MAC через ifconfig или ip
                try:
                    result = subprocess.run(
                        ['ifconfig'], capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        import re
                        mac_pattern = r'ether\s+([0-9a-f:]{17})'
                        matches = re.findall(mac_pattern, result.stdout.lower())
                        if matches:
                            return matches[0]
                except:
                    pass
            
            # Если не удалось получить MAC другими способами
            mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                           for elements in range(0, 8*6, 8)][::-1])
            if mac != "00:00:00:00:00:00":
                return mac
                
        except Exception as e:
            self.logger.error(f"Ошибка получения MAC-адреса: {e}")
        
        return None
    
    def generate_hardware_id_backup(self) -> str:
        """Резервная генерация HWID"""
        try:
            system_info = []
            
            # Информация о диске
            if psutil.disk_partitions():
                try:
                    # Пытаемся получить серийный номер диска (для Windows)
                    if platform.system() == "Windows":
                        result = subprocess.run(
                            ['wmic', 'diskdrive', 'get', 'serialnumber'],
                            capture_output=True, text=True, shell=True
                        )
                        if result.stdout:
                            lines = result.stdout.strip().split('\n')
                            for line in lines[1:]:  # Пропускаем заголовок
                                serial = line.strip()
                                if serial:
                                    system_info.append(serial)
                                    break
                except:
                    pass
            
            # Информация о системе
            system_info.append(platform.node())
            system_info.append(str(psutil.virtual_memory().total))
            
            # Информация о процессоре
            cpu_info = platform.processor()
            if cpu_info:
                system_info.append(cpu_info)
            
            # Создаем хэш
            combined = "-".join(system_info)
            hardware_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()
            
            return f"CRAFT-{hardware_hash}"
            
        except Exception as e:
            self.logger.error(f"Ошибка резервной генерации HWID: {e}")
            return f"CRAFT-{uuid.uuid4().hex[:20].upper()}"
    
    def load_license_data(self) -> bool:
        """Загрузка сохраненных данных лицензии"""
        try:
            if os.path.exists(self.license_file):
                with open(self.license_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    self.license_key = data.get('license_key')
                    self.expiry_date = data.get('expiry_date')
                    self.license_valid = data.get('license_valid', False)
                    
                    # Проверяем срок действия
                    if self.expiry_date:
                        try:
                            if 'Z' in self.expiry_date:
                                expiry_str = self.expiry_date.replace('Z', '+00:00')
                            else:
                                expiry_str = self.expiry_date
                            
                            expiry_dt = datetime.fromisoformat(expiry_str)
                            current_dt = datetime.utcnow()
                            
                            if current_dt < expiry_dt:
                                self.license_valid = True
                                self.logger.info(f"Лицензия действительна до {expiry_dt}")
                            else:
                                self.license_valid = False
                                self.logger.warning("Срок лицензии истек")
                        except Exception as e:
                            self.logger.error(f"Ошибка проверки даты: {e}")
                            self.license_valid = False
                    
                    self.logger.info(f"Загружена лицензия: {bool(self.license_key)}")
                    return True
                    
        except json.JSONDecodeError:
            self.logger.error("Файл лицензии поврежден")
        except Exception as e:
            self.logger.error(f"Ошибка загрузки: {e}")
        
        return False
    
    def save_license_data(self) -> bool:
        """Сохранение данных лицензии"""
        try:
            data = {
                'license_key': self.license_key,
                'hardware_id': self.hardware_id,
                'expiry_date': self.expiry_date,
                'license_valid': self.license_valid,
                'last_check': datetime.utcnow().isoformat(),
                'server_url': self.server_url
            }
            
            with open(self.license_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self.logger.info("Лицензия сохранена")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка сохранения: {e}")
            return False
    
    def validate_license(self, key: Optional[str] = None, 
                        hardware_id: Optional[str] = None) -> Dict[str, Any]:
        """Проверка лицензии на сервере"""
        try:
            check_key = key or self.license_key
            check_hwid = hardware_id or self.hardware_id
            
            if not check_key:
                return {
                    'valid': False,
                    'message': 'Не указан лицензионный ключ',
                    'error': True
                }
            
            if not check_hwid:
                return {
                    'valid': False,
                    'message': 'Не указан ID компьютера',
                    'error': True
                }
            
            self.logger.info(f"Проверка лицензии {check_key[:8]}... на HWID {check_hwid}")
            
            # Отправляем запрос на сервер
            response = requests.post(
                f"{self.server_url}/validate",
                json={
                    'key': check_key,
                    'hardware_id': check_hwid
                },
                timeout=10,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'CraftBot/7.2'
                }
            )
            
            self.logger.debug(f"Статус ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.logger.debug(f"Ответ сервера: {data}")
                
                if data.get('valid'):
                    # Обновляем данные
                    self.license_valid = True
                    self.expiry_date = data.get('expiry_date')
                    self.license_key = check_key
                    self.hardware_id = check_hwid
                    
                    # Сохраняем
                    self.save_license_data()
                    
                    self.logger.info("Лицензия действительна")
                    return {
                        'valid': True,
                        'expiry_date': self.expiry_date,
                        'message': 'Лицензия действительна'
                    }
                else:
                    error_msg = data.get('message', 'Лицензия недействительна')
                    self.logger.warning(f"Лицензия недействительна: {error_msg}")
                    return {
                        'valid': False,
                        'message': error_msg,
                        'error': True
                    }
                    
            elif response.status_code == 403:
                error_msg = "Лицензия заблокирована"
                try:
                    data = response.json()
                    error_msg = data.get('message', error_msg)
                except:
                    pass
                
                self.logger.error(error_msg)
                return {
                    'valid': False,
                    'message': error_msg,
                    'error': True
                }
                
            elif response.status_code == 404:
                error_msg = "Ключ не найден на сервере"
                self.logger.error(error_msg)
                return {
                    'valid': False,
                    'message': error_msg,
                    'error': True
                }
                
            elif response.status_code == 503:
                error_msg = "Сервер на техническом обслуживании"
                self.logger.warning(error_msg)
                return {
                    'valid': False,
                    'message': error_msg,
                    'error': True
                }
                
            else:
                error_msg = f"Ошибка сервера: {response.status_code}"
                try:
                    if response.text:
                        error_data = response.json()
                        error_msg = error_data.get('message', error_msg)
                except:
                    pass
                
                self.logger.error(error_msg)
                return {
                    'valid': False,
                    'message': error_msg,
                    'error': True
                }
                
        except requests.exceptions.ConnectionError:
            error_msg = "Нет подключения к серверу"
            self.logger.error(error_msg)
            return {
                'valid': False,
                'message': error_msg,
                'error': True
            }
            
        except requests.exceptions.Timeout:
            error_msg = "Таймаут подключения"
            self.logger.error(error_msg)
            return {
                'valid': False,
                'message': error_msg,
                'error': True
            }
            
        except Exception as e:
            error_msg = f"Ошибка проверки: {str(e)}"
            self.logger.error(error_msg)
            return {
                'valid': False,
                'message': error_msg,
                'error': True
            }
    
    def register_license(self, key: str) -> Dict[str, Any]:
        """Регистрация новой лицензии"""
        try:
            # Очищаем и проверяем ключ
            key = key.strip()
            
            # Проверка формата UUID
            uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            if not re.match(uuid_pattern, key.lower()):
                return {
                    'valid': False,
                    'message': 'Неверный формат ключа. Требуется UUID',
                    'error': True
                }
            
            self.logger.info(f"Регистрация ключа: {key[:8]}...")
            
            # Проверяем лицензию на сервере
            result = self.validate_license(key, self.hardware_id)
            
            if result.get('valid'):
                self.logger.info("Лицензия успешно активирована")
            else:
                self.logger.error(f"Ошибка активации: {result.get('message')}")
            
            return result
            
        except Exception as e:
            error_msg = f"Ошибка регистрации: {str(e)}"
            self.logger.error(error_msg)
            return {
                'valid': False,
                'message': error_msg,
                'error': True
            }
    
    def start_background_check(self):
        """Запуск фоновой проверки"""
        if self.license_check_running:
            return
        
        self.license_check_running = True
        self.license_check_thread = threading.Thread(
            target=self._background_check_loop,
            daemon=True,
            name="LicenseCheck"
        )
        self.license_check_thread.start()
        self.logger.info("Запущена фоновая проверка лицензии")
    
    def _background_check_loop(self):
        """Цикл фоновой проверки"""
        check_count = 0
        while self.license_check_running:
            try:
                time.sleep(self.license_check_interval)
                check_count += 1
                
                if self.license_key and self.hardware_id:
                    self.logger.debug(f"Фоновая проверка #{check_count}")
                    
                    result = self.validate_license()
                    if not result.get('valid'):
                        self.license_valid = False
                        self.logger.warning("Лицензия стала недействительной")
                        
                        # Вызываем callback если установлен
                        if self.on_license_invalid_callback:
                            try:
                                self.on_license_invalid_callback(result.get('message'))
                            except:
                                pass
                    
                    # Сохраняем состояние
                    self.save_license_data()
                    
            except Exception as e:
                self.logger.error(f"Ошибка в фоновой проверке: {e}")
    
    def stop_background_check(self):
        """Остановка фоновой проверки"""
        self.license_check_running = False
        if self.license_check_thread:
            self.license_check_thread.join(timeout=2)
        self.logger.info("Фоновая проверка остановлена")
    
    def set_license_invalid_callback(self, callback):
        """Установка callback для недействительной лицензии"""
        self.on_license_invalid_callback = callback
    
    def is_license_active(self) -> bool:
        """Проверка активности лицензии"""
        if not self.license_valid or not self.license_key:
            return False
        
        # Дополнительная проверка срока
        if self.expiry_date:
            try:
                if 'Z' in self.expiry_date:
                    expiry_str = self.expiry_date.replace('Z', '+00:00')
                else:
                    expiry_str = self.expiry_date
                
                expiry = datetime.fromisoformat(expiry_str)
                now = datetime.utcnow()
                
                # Добавляем запас в 5 минут
                if now >= expiry - timedelta(minutes=5):
                    self.license_valid = False
                    self.logger.warning("Срок лицензии скоро истекает или истек")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Ошибка проверки срока: {e}")
        
        return self.license_valid
    
    def reset_license(self):
        """Сброс лицензии"""
        self.logger.info("Сброс лицензии")
        
        self.license_key = None
        self.license_valid = False
        self.expiry_date = None
        
        # Останавливаем проверку
        self.stop_background_check()
        
        # Удаляем файл лицензии, но сохраняем HWID
        try:
            if os.path.exists(self.license_file):
                os.remove(self.license_file)
                self.logger.info("Файл лицензии удален")
        except Exception as e:
            self.logger.error(f"Ошибка удаления файла: {e}")
    
    def get_license_info(self) -> Dict[str, Any]:
        """Получение информации о лицензии"""
        return {
            'has_license': bool(self.license_key),
            'key': self.license_key,
            'key_short': f"{self.license_key[:8]}...{self.license_key[-4:]}" if self.license_key else None,
            'hardware_id': self.hardware_id,
            'expiry_date': self.expiry_date,
            'is_valid': self.license_valid,
            'is_active': self.is_license_active(),
            'server_url': self.server_url,
            'check_interval': self.license_check_interval
        }
