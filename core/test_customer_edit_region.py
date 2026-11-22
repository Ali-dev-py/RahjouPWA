from types import SimpleNamespace as Obj
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, RequestFactory
from .views import CustomerEditView


class CustomerEditRegionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.customer = Obj(customerid=1, gcustomerid='C1', custname='مشتری', mobile='', phone='',
                            address='', gareageoghrafiid='{REGION-1}', save=MagicMock())
        self.area = Obj(gareageographyid='REGION-1', name='منطقه اول')
        self.other = Obj(gareageographyid='REGION-2', name='منطقه دوم')
        self.group = Obj(customergroupid=1, gcustomergroupid='G1', groupname='گروه', gcompanyid='COMP')
        self.view = CustomerEditView()
        for target, value in (('_get_customer', self.customer), ('_get_customer_group_link', None)):
            patcher = patch.object(self.view, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('core.views._area_rows', return_value=[self.area, self.other])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('core.views.Customergroup')
        groups = patcher.start()
        self.addCleanup(patcher.stop)
        groups.objects.using.return_value.all.return_value.order_by.return_value = [self.group]
        groups.objects.using.return_value.filter.return_value.first.return_value = self.group

    def request(self, data):
        request = self.factory.post('/', data)
        request.plus_user = Obj(uname='کاربر')
        return request

    def test_get_prefills_normalized_region(self):
        response = self.view.get(self.factory.get('/'), pk='C1')
        self.assertContains(response, 'id="area_id"')
        self.assertContains(response, 'value="region-1" selected')
        self.assertContains(response, 'منطقه اول')

    @patch('core.views.Customer2Group')
    @patch('core.views.transaction.atomic')
    def test_change_clear_and_omitted_region(self, atomic, links):
        for area, expected in (('REGION-2', 'REGION-2'), ('', None), (None, 'KEEP')):
            self.customer.gareageoghrafiid = 'KEEP'
            self.customer.save.reset_mock()
            data = {'custname': 'نام جدید', 'customer_group': 'G1'}
            if area is not None:
                data['area_id'] = area
            response = self.view.post(self.request(data), pk='C1')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.customer.gareageoghrafiid, expected)
            fields = self.customer.save.call_args.kwargs['update_fields']
            self.assertEqual('gareageoghrafiid' in fields, area is not None)

    def test_invalid_region_rejected_without_writes(self):
        response = self.view.post(self.request({'custname': 'نام جدید', 'customer_group': 'G1', 'area_id': 'OTHER'}), pk='C1')
        self.assertContains(response, 'منطقه انتخاب‌شده معتبر نیست.')
        self.customer.save.assert_not_called()
        self.assertEqual(self.customer.gareageoghrafiid, '{REGION-1}')

    def test_selected_region_retained_on_other_validation_error(self):
        response = self.view.post(self.request({'custname': '', 'customer_group': 'G1', 'area_id': '{REGION-2}'}), pk='C1')
        self.assertContains(response, 'نام مشتری الزامی است.')
        self.assertContains(response, 'value="region-2" selected')
        self.customer.save.assert_not_called()
