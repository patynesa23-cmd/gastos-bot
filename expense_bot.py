import logging
import re
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ExpenseBot:
    def __init__(self, telegram_token: str, google_credentials: str, spreadsheet_key: str):
        self.telegram_token = telegram_token
        self.google_credentials = google_credentials
        self.spreadsheet_key = spreadsheet_key
        
        # Inicializar Google Sheets
        self.setup_google_sheets()
        
        # Categorías predefinidas
        self.categories = {
            'comida': ['restaurante', 'comida', 'cena', 'almuerzo', 'desayuno', 'pizza', 'burger', 'café', 'bar'],
            'transporte': ['uber', 'taxi', 'metro', 'bus', 'gasolina', 'combustible', 'parking'],
            'entretenimiento': ['cine', 'teatro', 'concierto', 'juego', 'netflix', 'spotify'],
            'compras': ['tienda', 'ropa', 'zapatos', 'amazon', 'mercado', 'supermercado'],
            'servicios': ['luz', 'agua', 'gas', 'internet', 'teléfono', 'streaming'],
            'salud': ['doctor', 'farmacia', 'medicina', 'hospital', 'dentista'],
            'educación': ['curso', 'libro', 'universidad', 'academia'],
            'otros': []
        }
    
    def setup_google_sheets(self):
        """Configurar conexión con Google Sheets"""
        try:
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/spreadsheets']
            
            # Si google_credentials es un path a archivo, usarlo como archivo
            # Si es un JSON string, parsearlo directamente
            if os.path.exists(self.google_credentials):
                creds = Credentials.from_service_account_file(
                    self.google_credentials, scopes=scope)
            else:
                # Asumir que es JSON string (para deployment)
                credentials_info = json.loads(self.google_credentials)
                creds = Credentials.from_service_account_info(
                    credentials_info, scopes=scope)
            
            self.gc = gspread.authorize(creds)
            self.spreadsheet = self.gc.open_by_key(self.spreadsheet_key)
            
            # Configurar hojas
            self.setup_sheets()
            
        except Exception as e:
            logger.error(f"Error configurando Google Sheets: {e}")
            raise
    
    def parse_expense(self, message: str) -> Optional[Tuple[float, str]]:
        """Extraer cantidad y descripción del mensaje"""
        # Patrones para detectar gastos
        patterns = [
            r'(\d+(?:[,.]?\d+)?)\s*€?\s*(.+)',  # "50 café con María"
            r'(\d+(?:[,.]?\d+)?)\s*pesos?\s*(.+)',  # "50 pesos almuerzo"
            r'(\d+(?:[,.]?\d+)?)\s*\$\s*(.+)',  # "50$ cena"
            r'(.+?)\s*(\d+(?:[,.]?\d+)?)\s*€?',  # "almuerzo 50"
            r'(.+?)\s*(\d+(?:[,.]?\d+)?)\s*pesos?',  # "almuerzo 50 pesos"
        ]
        
        for pattern in patterns:
            match = re.match(pattern, message.strip(), re.IGNORECASE)
            if match:
                groups = match.groups()
                
                # Determinar cuál grupo es la cantidad y cuál la descripción
                try:
                    amount = float(groups[0].replace(',', '.'))
                    description = groups[1].strip()
                    return amount, description
                except ValueError:
                    try:
                        amount = float(groups[1].replace(',', '.'))
                        description = groups[0].strip()
                        return amount, description
                    except ValueError:
                        continue
        
        return None
    
    def categorize_expense(self, description: str) -> str:
        """Categorizar gasto automáticamente"""
        description_lower = description.lower()
        
        for category, keywords in self.categories.items():
            if any(keyword in description_lower for keyword in keywords):
                return category
        
        return 'otros'
    
    def setup_sheets(self):
        """Configurar hojas del spreadsheet con formato visual"""
        try:
            # Obtener o crear hojas
            worksheet_names = [ws.title for ws in self.spreadsheet.worksheets()]
            
            # Hoja de Gastos
            if 'Gastos' not in worksheet_names:
                self.expenses_sheet = self.spreadsheet.add_worksheet(title="Gastos", rows="1000", cols="10")
            else:
                self.expenses_sheet = self.spreadsheet.worksheet('Gastos')
            
            # Hoja de Ingresos
            if 'Ingresos' not in worksheet_names:
                self.income_sheet = self.spreadsheet.add_worksheet(title="Ingresos", rows="1000", cols="8")
            else:
                self.income_sheet = self.spreadsheet.worksheet('Ingresos')
            
            # Hoja de Dashboard
            if 'Dashboard' not in worksheet_names:
                self.dashboard_sheet = self.spreadsheet.add_worksheet(title="Dashboard", rows="50", cols="15")
            else:
                self.dashboard_sheet = self.spreadsheet.worksheet('Dashboard')
            
            # Configurar headers y formato
            self.setup_expenses_sheet()
            self.setup_income_sheet()
            self.setup_dashboard()
            
        except Exception as e:
            logger.error(f"Error configurando hojas: {e}")
            # Fallback a la primera hoja
            self.expenses_sheet = self.spreadsheet.sheet1
            self.income_sheet = self.spreadsheet.sheet1
            self.dashboard_sheet = self.spreadsheet.sheet1
    
    def setup_expenses_sheet(self):
        """Configurar la hoja de gastos con formato"""
        headers = ['Fecha', 'Descripción', 'Cantidad', 'Categoría', 'Usuario', 'Tipo', 'Mes', 'Año']
        
        # Verificar si ya hay headers
        existing_headers = self.expenses_sheet.row_values(1)
        if not existing_headers:
            self.expenses_sheet.append_row(headers)
        
        # Aplicar formato a los headers
        self.format_headers(self.expenses_sheet, len(headers))
        
        # Configurar formato condicional para montos altos
        self.apply_conditional_formatting(self.expenses_sheet)
    
    def setup_income_sheet(self):
        """Configurar la hoja de ingresos con formato"""
        headers = ['Fecha', 'Descripción', 'Cantidad', 'Fuente', 'Usuario', 'Mes', 'Año']
        
        # Verificar si ya hay headers
        existing_headers = self.income_sheet.row_values(1)
        if not existing_headers:
            self.income_sheet.append_row(headers)
        
        # Aplicar formato a los headers
        self.format_headers(self.income_sheet, len(headers))
    
    def setup_dashboard(self):
        """Configurar la hoja de dashboard"""
        # Crear títulos y estructura del dashboard
        dashboard_structure = [
            ['📊 CONTROL DE GASTOS - DASHBOARD', '', '', '', '', '', '', '', '', ''],
            ['', '', '', '', '', '', '', '', '', ''],
            ['💰 RESUMEN MENSUAL', '', '', '📈 INGRESOS VS GASTOS', '', '', '🏷️ POR CATEGORÍA', '', '', ''],
            ['Mes:', '', '', 'Ingresos:', '', '', 'Comida:', '', '', ''],
            ['Total Gastos:', '', '', 'Gastos:', '', '', 'Transporte:', '', '', ''],
            ['Total Ingresos:', '', '', 'Diferencia:', '', '', 'Entretenimiento:', '', '', ''],
            ['Balance:', '', '', '', '', '', 'Compras:', '', '', ''],
            ['', '', '', '', '', '', 'Servicios:', '', '', ''],
            ['', '', '', '', '', '', 'Salud:', '', '', ''],
            ['', '', '', '', '', '', 'Educación:', '', '', ''],
            ['', '', '', '', '', '', 'Otros:', '', '', ''],
        ]
        
        # Escribir estructura si está vacía
        if not self.dashboard_sheet.row_values(1):
            for i, row in enumerate(dashboard_structure, 1):
                self.dashboard_sheet.append_row(row)
        
        # Aplicar formato al dashboard
        self.format_dashboard()
    
    def format_headers(self, sheet, num_cols):
        """Aplicar formato a los headers"""
        try:
            # Formato para la primera fila (headers)
            sheet.format('1:1', {
                'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.8},
                'textFormat': {
                    'bold': True,
                    'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}
                },
                'horizontalAlignment': 'CENTER',
                'borders': {
                    'top': {'style': 'SOLID'},
                    'bottom': {'style': 'SOLID'},
                    'left': {'style': 'SOLID'},
                    'right': {'style': 'SOLID'}
                }
            })
            
            # Congelar la primera fila
            sheet.freeze(rows=1)
            
        except Exception as e:
            logger.error(f"Error aplicando formato a headers: {e}")
    
    def apply_conditional_formatting(self, sheet):
        """Aplicar formato condicional para gastos altos"""
        try:
            # Usar la API correcta para formato condicional
            requests = [{
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{'sheetId': sheet.id, 'startRowIndex': 1, 'startColumnIndex': 2, 'endColumnIndex': 3}],
                        'booleanRule': {
                            'condition': {
                                'type': 'NUMBER_GREATER',
                                'values': [{'userEnteredValue': '100'}]
                            },
                            'format': {
                                'backgroundColor': {'red': 1.0, 'green': 0.8, 'blue': 0.8}
                            }
                        }
                    },
                    'index': 0
                }
            }]
            
            body = {'requests': requests}
            self.spreadsheet.batch_update(body)
            
        except Exception as e:
            logger.error(f"Error aplicando formato condicional: {e}")
            # Continuar sin formato condicional si falla
    
    def format_dashboard(self):
        """Aplicar formato visual al dashboard"""
        try:
            # Título principal
            self.dashboard_sheet.format('A1:J1', {
                'backgroundColor': {'red': 0.1, 'green': 0.3, 'blue': 0.7},
                'textFormat': {
                    'bold': True,
                    'fontSize': 16,
                    'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}
                },
                'horizontalAlignment': 'CENTER'
            })
            
            # Secciones del dashboard
            sections = ['A3:C3', 'D3:F3', 'G3:J3']
            colors = [
                {'red': 0.8, 'green': 0.9, 'blue': 0.8},  # Verde claro
                {'red': 0.9, 'green': 0.8, 'blue': 0.8},  # Rojo claro  
                {'red': 0.8, 'green': 0.8, 'blue': 0.9}   # Azul claro
            ]
            
            for section, color in zip(sections, colors):
                self.dashboard_sheet.format(section, {
                    'backgroundColor': color,
                    'textFormat': {'bold': True},
                    'horizontalAlignment': 'CENTER',
                    'borders': {
                        'top': {'style': 'SOLID'},
                        'bottom': {'style': 'SOLID'},
                        'left': {'style': 'SOLID'},
                        'right': {'style': 'SOLID'}
                    }
                })
            
        except Exception as e:
            logger.error(f"Error formateando dashboard: {e}")
    
    def parse_income(self, message: str) -> Optional[Tuple[float, str]]:
        """Extraer cantidad y descripción de un ingreso"""
        # Patrones similares a gastos pero para ingresos
        patterns = [
            r'ingreso\s+(\d+(?:[,.]?\d+)?)\s*€?\s*(.+)',  # "ingreso 1500 salario"
            r'ingreso\s+(\d+(?:[,.]?\d+)?)\s*pesos?\s*(.+)',
            r'cobré\s+(\d+(?:[,.]?\d+)?)\s*€?\s*(.+)',  # "cobré 500 freelance"
            r'cobré\s+(\d+(?:[,.]?\d+)?)\s*pesos?\s*(.+)',
            r'entrada\s+(\d+(?:[,.]?\d+)?)\s*€?\s*(.+)',  # "entrada 200 venta"
        ]
        
        for pattern in patterns:
            match = re.match(pattern, message.strip(), re.IGNORECASE)
            if match:
                try:
                    amount = float(match.group(1).replace(',', '.'))
                    description = match.group(2).strip()
                    return amount, description
                except ValueError:
                    continue
        
        return None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        welcome_message = """
¡Hola! 👋 Soy tu bot de control de gastos e ingresos.

📝 **Cómo usarme:**
• **Gastos**: "50 almuerzo", "café 3.50€", "20 pesos uber"
• **Ingresos**: "ingreso 1500 salario", "cobré 500 freelance"
• Te ayudo a categorizarlos automáticamente
• Todo se guarda en tu spreadsheet con formato visual

🔧 **Comandos disponibles:**
/start - Ver este mensaje
/categorias - Ver categorías disponibles
/resumen - Resumen del mes actual (actualiza dashboard)
/help - Ayuda detallada

📊 **Nuevo**: Dashboard visual con balance mensual y análisis por categoría

¡Empezá a enviar tus gastos e ingresos! 💰💵
        """
        await update.message.reply_text(welcome_message)
    
    async def show_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mostrar categorías disponibles"""
        message = "📋 **Categorías disponibles:**\n\n"
        for category, keywords in self.categories.items():
            if keywords:
                message += f"• **{category.title()}**: {', '.join(keywords[:5])}\n"
            else:
                message += f"• **{category.title()}**\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def get_monthly_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Obtener resumen mensual y actualizar dashboard"""
        try:
            current_month = datetime.now().strftime("%Y-%m")
            
            # Obtener gastos
            try:
                expense_records = self.expenses_sheet.get_all_records()
            except:
                expense_records = []
            
            # Obtener ingresos
            try:
                income_records = self.income_sheet.get_all_records()
            except:
                income_records = []
            
            monthly_expenses = [record for record in expense_records 
                             if record.get('Fecha', '').startswith(current_month)]
            
            monthly_income = [record for record in income_records 
                            if record.get('Fecha', '').startswith(current_month)]
            
            # Calcular totales
            total_spent = sum(float(exp.get('Cantidad', 0)) for exp in monthly_expenses)
            total_income = sum(float(inc.get('Cantidad', 0)) for inc in monthly_income)
            balance = total_income - total_spent
            
            # Calcular totales por categoría
            category_totals = {}
            for expense in monthly_expenses:
                category = expense.get('Categoría', 'otros')
                amount = float(expense.get('Cantidad', 0))
                category_totals[category] = category_totals.get(category, 0) + amount
            
            # Actualizar dashboard
            self.update_dashboard(current_month, total_spent, total_income, balance, category_totals)
            
            # Crear mensaje de resumen
            summary = f"📊 **Resumen de {current_month}**\n\n"
            summary += f"💰 **Total gastado**: {total_spent:.2f}€\n"
            summary += f"💵 **Total ingresos**: {total_income:.2f}€\n"
            summary += f"📈 **Balance**: {balance:.2f}€\n\n"
            
            if category_totals:
                summary += "📋 **Por categoría:**\n"
                for category, amount in sorted(category_totals.items(), 
                                             key=lambda x: x[1], reverse=True):
                    percentage = (amount / total_spent) * 100 if total_spent > 0 else 0
                    summary += f"• {category.title()}: {amount:.2f}€ ({percentage:.1f}%)\n"
            
            summary += f"\n📊 Dashboard actualizado en Google Sheets!"
            
            await update.message.reply_text(summary, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error obteniendo resumen: {e}")
            await update.message.reply_text("Error obteniendo el resumen. Intentá más tarde.")
    
    def update_dashboard(self, month, total_expenses, total_income, balance, category_totals):
        """Actualizar el dashboard con los datos actuales"""
        try:
            # Actualizar datos del resumen mensual
            updates = [
                {'range': 'B4', 'values': [[month]]},
                {'range': 'B5', 'values': [[f"{total_expenses:.2f}€"]]},
                {'range': 'B6', 'values': [[f"{total_income:.2f}€"]]},
                {'range': 'B7', 'values': [[f"{balance:.2f}€"]]},
                
                # Sección ingresos vs gastos
                {'range': 'E4', 'values': [[f"{total_income:.2f}€"]]},
                {'range': 'E5', 'values': [[f"{total_expenses:.2f}€"]]},
                {'range': 'E6', 'values': [[f"{balance:.2f}€"]]},
            ]
            
            # Categorías
            categories_order = ['comida', 'transporte', 'entretenimiento', 'compras', 'servicios', 'salud', 'educación', 'otros']
            for i, category in enumerate(categories_order):
                amount = category_totals.get(category, 0)
                updates.append({'range': f'H{4+i}', 'values': [[f"{amount:.2f}€"]]})
            
            # Aplicar todas las actualizaciones
            self.dashboard_sheet.batch_update(updates)
            
            # Colorear balance según si es positivo o negativo
            balance_color = {'red': 0.8, 'green': 0.9, 'blue': 0.8} if balance >= 0 else {'red': 1.0, 'green': 0.8, 'blue': 0.8}
            self.dashboard_sheet.format('B7', {'backgroundColor': balance_color})
            self.dashboard_sheet.format('E6', {'backgroundColor': balance_color})
            
        except Exception as e:
            logger.error(f"Error actualizando dashboard: {e}")
    
    async def handle_expense(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Procesar mensaje de gasto o ingreso"""
        try:
            message_text = update.message.text
            
            # Verificar si es un ingreso
            income_data = self.parse_income(message_text)
            if income_data:
                await self.handle_income(update, income_data)
                return
            
            # Si no es ingreso, procesar como gasto
            expense_data = self.parse_expense(message_text)
            
            if not expense_data:
                await update.message.reply_text(
                    "No pude entender el mensaje. Intentá con:\n"
                    "• Gastos: '50 almuerzo' o 'café 3.50€'\n"
                    "• Ingresos: 'ingreso 1500 salario' o 'cobré 500 freelance'"
                )
                return
            
            amount, description = expense_data
            suggested_category = self.categorize_expense(description)
            
            # Crear botones para categorización
            keyboard = []
            for category in self.categories.keys():
                emoji = "✅" if category == suggested_category else ""
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {category.title()}", 
                    callback_data=f"cat_{category}_{amount}_{description}"
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💰 **Gasto registrado**: {amount:.2f}€\n"
                f"📝 **Descripción**: {description}\n"
                f"🏷️ **Categoría sugerida**: {suggested_category.title()}\n\n"
                f"¿Confirmar categoría o elegir otra?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
            await update.message.reply_text("Error procesando el mensaje. Intentá nuevamente.")
    
    async def handle_income(self, update: Update, income_data: Tuple[float, str]):
        """Procesar un ingreso"""
        try:
            amount, description = income_data
            
            # Fuentes comunes de ingreso
            income_sources = ['salario', 'freelance', 'venta', 'bono', 'intereses', 'regalo', 'otros']
            
            # Sugerir fuente basada en descripción
            suggested_source = 'otros'
            description_lower = description.lower()
            for source in income_sources:
                if source in description_lower:
                    suggested_source = source
                    break
            
            # Crear botones para fuente de ingreso
            keyboard = []
            for source in income_sources:
                emoji = "✅" if source == suggested_source else ""
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {source.title()}", 
                    callback_data=f"inc_{source}_{amount}_{description}"
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💵 **Ingreso registrado**: {amount:.2f}€\n"
                f"📝 **Descripción**: {description}\n"
                f"🏷️ **Fuente sugerida**: {suggested_source.title()}\n\n"
                f"¿Confirmar fuente o elegir otra?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error procesando ingreso: {e}")
            await update.message.reply_text("Error procesando el ingreso. Intentá nuevamente.")
    
    async def handle_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manejar selección de categoría o fuente"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Parsear datos del callback
            data_parts = query.data.split('_', 3)
            type_prefix = data_parts[0]  # 'cat' para categoría, 'inc' para ingreso
            category_or_source = data_parts[1]
            amount = float(data_parts[2])
            description = data_parts[3]
            
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            username = update.effective_user.username or update.effective_user.first_name
            current_date = datetime.now()
            month = current_date.strftime("%Y-%m")
            year = current_date.strftime("%Y")
            
            if type_prefix == 'cat':  # Gasto
                row_data = [date_str, description, amount, category_or_source, username, 'Gasto', month, year]
                self.expenses_sheet.append_row(row_data)
                
                await query.edit_message_text(
                    f"✅ **Gasto guardado exitosamente**\n\n"
                    f"💰 **Cantidad**: {amount:.2f}€\n"
                    f"📝 **Descripción**: {description}\n"
                    f"🏷️ **Categoría**: {category_or_source.title()}\n"
                    f"📅 **Fecha**: {date_str}",
                    parse_mode='Markdown'
                )
                
            elif type_prefix == 'inc':  # Ingreso
                row_data = [date_str, description, amount, category_or_source, username, month, year]
                self.income_sheet.append_row(row_data)
                
                await query.edit_message_text(
                    f"✅ **Ingreso guardado exitosamente**\n\n"
                    f"💵 **Cantidad**: {amount:.2f}€\n"
                    f"📝 **Descripción**: {description}\n"
                    f"🏷️ **Fuente**: {category_or_source.title()}\n"
                    f"📅 **Fecha**: {date_str}",
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error guardando registro: {e}")
            await query.edit_message_text("Error guardando el registro. Intentá nuevamente.")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando de ayuda"""
        help_text = """
🤖 **Ayuda - Bot de Control de Gastos**

💰 **Formatos para GASTOS:**
• "50 almuerzo con Juan"
• "café 3.50€"
• "20 pesos uber al trabajo"
• "compras supermercado 85"

💵 **Formatos para INGRESOS:**
• "ingreso 1500 salario"
• "cobré 500 freelance"
• "entrada 200 venta algo"

🏷️ **Categorización automática:**
• El bot sugiere categorías y fuentes automáticamente
• Podés elegir manualmente la correcta
• Se aprende de palabras clave

📊 **Seguimiento visual:**
• Spreadsheet con 3 hojas: Gastos, Ingresos, Dashboard
• Dashboard actualizado automáticamente
• Formato visual con colores y bordes
• Resúmenes mensuales con balance

🔧 **Comandos:**
/start - Mensaje de bienvenida
/categorias - Ver categorías disponibles
/resumen - Resumen completo del mes (actualiza dashboard)
/help - Esta ayuda

📈 **Dashboard incluye:**
• Balance mensual (ingresos - gastos)
• Análisis por categoría
• Indicadores visuales (verde/rojo según balance)

¿Problemas? Asegurate de que el bot tenga acceso a tu Google Sheets.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    def run(self):
        """Ejecutar el bot"""
        try:
            application = Application.builder().token(self.telegram_token).build()
            
            # Handlers
            application.add_handler(CommandHandler("start", self.start))
            application.add_handler(CommandHandler("categorias", self.show_categories))
            application.add_handler(CommandHandler("resumen", self.get_monthly_summary))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CallbackQueryHandler(self.handle_category_selection))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_expense))
            
            logger.info("Bot iniciado")
            application.run_polling(poll_interval=1, timeout=10)
            
        except Exception as e:
            logger.error(f"Error ejecutando bot: {e}")
            raise

if __name__ == "__main__":
    try:
        # Configuración - Variables de entorno
        TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
        # Priorizar GOOGLE_CREDENTIALS sobre GOOGLE_CREDENTIALS_FILE
        GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS") or os.getenv("GOOGLE_CREDENTIALS_FILE")
        SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
        
        # Validar que las variables existan
        if not TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN no está definido en las variables de entorno")
        if not GOOGLE_CREDENTIALS:
            raise ValueError("GOOGLE_CREDENTIALS o GOOGLE_CREDENTIALS_FILE no está definido en las variables de entorno") 
        if not SPREADSHEET_KEY:
            raise ValueError("SPREADSHEET_KEY no está definido en las variables de entorno")
        
        logger.info("Iniciando bot de gastos...")
        bot = ExpenseBot(TELEGRAM_TOKEN, GOOGLE_CREDENTIALS, SPREADSHEET_KEY)
        logger.info("Google Sheets configurado correctamente")
        bot.run()
        
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        raise
