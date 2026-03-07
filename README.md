# Proyección App Django

Dashboard financiero institucional reconstruido en Django a partir del flujo original en Streamlit, con autenticación, persistencia en SQLite/PostgreSQL-ready, importación desde Excel y edición de datos.

## Stack
- Django 5
- SQLite (por defecto)
- PostgreSQL opcional vía variables de entorno (`POSTGRES_*`)
- Pandas + OpenPyXL para importación inicial

## Instalación
1. Crear/activar entorno virtual
2. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Migrar base:
   ```bash
   python manage.py migrate
   ```
4. Crear superusuario:
   ```bash
   python manage.py createsuperuser
   ```
5. Crear grupos/permisos base:
   ```bash
   python manage.py bootstrap_roles
   ```

## Importación Excel
### Opción 1: comando
```bash
python manage.py import_excel_data --path "PROYECCION 2026 (4).xlsx" --scenario "ESCENARIO 1" --year 2026 --start-month 3
```

### Opción 2: web
- Ingresar con usuario staff
- Ir a `/importar-excel/`
- Subir archivo y ejecutar importación

## Correr servidor
```bash
python manage.py runserver
```

## Usuarios y permisos
- `administrador_finanzas`: acceso completo de negocio
- `operador_finanzas`: visualización + edición de gastos/ingresos

## Estructura
- `dashboard/models.py`: entidades base
- `dashboard/services/excel_importer.py`: importador y normalización
- `dashboard/services/dashboard_logic.py`: cálculos del dashboard
- `dashboard/views.py`: vistas autenticadas, filtros y edición
- `dashboard/templates/dashboard/`: UI principal
- `dashboard/management/commands/`: bootstrap de roles + importador CLI
