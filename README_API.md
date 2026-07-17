# Ventas por Cliente

Este modulo expone una interfaz y una API con FastAPI para el reporte de ventas por cliente.

## APIs consumidas

Clientes:

```text
http://35.239.247.220:8001/clientes
```

Pagos:

```text
http://34.176.33.216:8000/payments/view-payments
```

Por defecto se consume:

```text
http://34.176.33.216:8000/payments/view-payments?status=PAGADO
```

Esto permite contar solo pagos reales y no reembolsos.

## Filtros disponibles en API de pagos

```text
?day=true
?week=true
?rental_id=1
?status=PAGADO
?status=REEMBOLSO
```

## Ejecutar localmente

```bash
pip install -r requirements.txt
python -m uvicorn Main:app --host 127.0.0.1 --port 8000
```

Interfaz:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Tema del silabo implementado

Se implemento tolerancia a fallas y recuperacion de fallas.

Si una API externa falla, el sistema intenta mantener disponible la interfaz usando el ultimo reporte valido guardado en cache de memoria. La interfaz consulta automaticamente cada 3 segundos para reflejar cambios recientes.
