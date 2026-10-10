"""
Сверка плиток главной с дашбордами: открывает каждый дашборд с фильтрами по умолчанию
и сравнивает цифры с главной. Запускать после правок дашбордов или главной.

    python manage.py check_figures
"""

import json

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.test import Client
from django.test.utils import setup_test_environment


class Command(BaseCommand):
    help = "Сверить плитки главной с дашбордами (выручка, наряды, прогноз, номенклатура, сезонность)"

    def handle(self, *args, **options):
        setup_test_environment()
        user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
        if not user:
            raise CommandError("Нужен активный суперпользователь")
        c = Client()
        c.force_login(user)
        H = {'HTTP_HOST': '127.0.0.1'}
        home = c.get('/admin/', **H).context
        s, fc, cat = home['sales'], home['forecast'], home['catalog']
        ok = lambda a, b, tol=0.5: '✓' if a is not None and b is not None and abs(float(a) - float(b)) <= tol else '✗'
        rows = []
        ov = c.get('/admin/sales/dashboard/overview/', **H).context
        k = ov['kpis'][0]
        rows += [('Выручка', s['revenue'], k['value'], ok(s['revenue'], k['value'])),
                 ('Выручка к прошлому году', s['revenue_yoy'], k['yoy'], ok(s['revenue_yoy'], k['yoy'], 1e-9)),
                 ('Период', s['period'], ov['f'].period.label, '✓' if s['period'] == ov['f'].period.label else '✗')]
        sv = c.get('/admin/sales/dashboard/service/', **H).context
        k = sv['kpis'][0]
        rows += [('Наряды', s['orders'], k['value'], ok(s['orders'], k['value'])),
                 ('Наряды к прошлому году', s['orders_yoy'], k['yoy'], ok(s['orders_yoy'], k['yoy'], 1e-9))]
        fo = c.get('/admin/forecast/dashboard/', **H).context
        k6 = [k for k in fo['kpis'] if k['title'].count('–') and k is not fo['kpis'][0]][-1]
        rows += [('Прогноз 6 мес.', fc['sum6'], k6['value'], ok(fc['sum6'], k6['value'])),
                 ('Ошибка 6 мес. (прогноз)', fc['error6'], fo['acc']['sum6'], ok(fc['error6'], fo['acc']['sum6'], 1e-9))]
        bt = c.get('/admin/forecast/dashboard/backtest/', **H).context
        rows += [('Ошибка 6 мес. (проверка)', fc['error6'], bt['acc']['sum6'], ok(fc['error6'], bt['acc']['sum6'], 1e-9))]
        gr = c.get('/admin/catalog/itemgroup/', **H).context['group_kpis']
        rows += [('Артикулов', cat['items'], int(gr[0]['sub'].split(':')[1].replace(' ', '').replace(' ','')), ''),
                 ('Не распознано', cat['unknown'], int(gr[1]['value'].replace(' ', '')), '')]
        rows[-2] = rows[-2][:3] + (ok(rows[-2][1], rows[-2][2]),); rows[-1] = rows[-1][:3] + (ok(rows[-1][1], rows[-1][2]),)
        for r in home['season']['rows']:
            se = c.get(r['url'], **H).context
            avg = json.loads(se['chart_profile'][0])['datasets'][0]['data']
            rows += [(f'Сезон {r["label"]}: профиль', [b['share'] for b in r['bars']][:4], avg[:4],
                      '✓' if [b['share'] for b in r['bars']] == avg else '✗')]

        bad = 0
        for name, a, b, mark in rows:
            line = f"{mark} {name:28} главная: {a}   дашборд: {b}"
            if mark == "✓":
                self.stdout.write(line)
            else:
                bad += 1
                self.stdout.write(self.style.ERROR(line))
        if bad:
            raise CommandError(f"Не сходится: {bad}")
        self.stdout.write(self.style.SUCCESS("Всё сходится"))
