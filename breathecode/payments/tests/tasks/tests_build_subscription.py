"""
Test /answer
"""
import logging
import random
from unittest.mock import MagicMock, call, patch

from django.utils import timezone
from breathecode.payments import tasks

from ...tasks import build_subscription

from ..mixins import PaymentsTestCase
from dateutil.relativedelta import relativedelta

UTC_NOW = timezone.now()


def subscription_item(data={}):
    return {
        'id': 1,
        'selected_cohort_set_id': None,
        'selected_event_type_set_id': None,
        'selected_mentorship_service_set_id': None,
        'academy_id': 1,
        'is_refundable': True,
        'paid_at': UTC_NOW,
        'pay_every': 1,
        'pay_every_unit': 'MONTH',
        'status': 'ACTIVE',
        'status_message': None,
        'user_id': 1,
        'valid_until': UTC_NOW,
        **data,
    }


#FIXME: create_v2 fail in this test file
class PaymentsTestSuite(PaymentsTestCase):
    """
    🔽🔽🔽 Bag not found
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    def test_bag_not_found(self):
        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [])

        self.assertEqual(logging.Logger.info.call_args_list, [call('Starting build_subscription for bag 1')])
        self.assertEqual(logging.Logger.error.call_args_list, [call('Bag with id 1 not found')])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [])

    """
    🔽🔽🔽 With Bag
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    def test_invoice_not_found(self):
        bag = {'status': 'PAID', 'was_delivered': False}
        model = self.bc.database.create_v2(bag=bag)

        # remove prints from mixer
        logging.Logger.info.call_args_list = []
        logging.Logger.error.call_args_list = []

        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [])

        self.assertEqual(logging.Logger.info.call_args_list, [call('Starting build_subscription for bag 1')])
        self.assertEqual(logging.Logger.error.call_args_list, [call('Invoice with id 1 not found')])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [self.bc.format.to_dict(model.bag)])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [])

    """
    🔽🔽🔽 With Bag and Invoice
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    @patch.object(timezone, 'now', MagicMock(return_value=UTC_NOW))
    @patch('breathecode.payments.tasks.build_service_stock_scheduler_from_subscription.delay', MagicMock())
    def test_subscription_was_created(self):
        bag = {
            'status': 'PAID',
            'was_delivered': False,
            'chosen_period': random.choice(['MONTH', 'QUARTER', 'HALF', 'YEAR']),
        }
        invoice = {'status': 'FULFILLED'}
        months = 1

        if bag['chosen_period'] == 'QUARTER':
            months = 3

        elif bag['chosen_period'] == 'HALF':
            months = 6

        elif bag['chosen_period'] == 'YEAR':
            months = 12

        model = self.bc.database.create(bag=bag, invoice=invoice)

        # remove prints from mixer
        logging.Logger.info.call_args_list = []
        logging.Logger.error.call_args_list = []

        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [])

        self.assertEqual(logging.Logger.info.call_args_list, [
            call('Starting build_subscription for bag 1'),
            call('Subscription was created with id 1'),
        ])
        self.assertEqual(logging.Logger.error.call_args_list, [])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [
            {
                **self.bc.format.to_dict(model.bag),
                'was_delivered': True,
            },
        ])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [
            self.bc.format.to_dict(model.invoice),
        ])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [
            subscription_item({
                'paid_at': model.invoice.paid_at,
                'valid_until': None,
                'next_payment_at': model.invoice.paid_at + relativedelta(months=months),
            }),
        ])

        self.assertEqual(tasks.build_service_stock_scheduler_from_subscription.delay.call_args_list, [
            call(1),
        ])

    """
    🔽🔽🔽 With Bag, Invoice and Cohort
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    @patch.object(timezone, 'now', MagicMock(return_value=UTC_NOW))
    @patch('breathecode.payments.tasks.build_service_stock_scheduler_from_subscription.delay', MagicMock())
    def test_subscription_was_created__bag_with_cohort(self):
        bag = {
            'status': 'PAID',
            'was_delivered': False,
            'chosen_period': random.choice(['MONTH', 'QUARTER', 'HALF', 'YEAR']),
        }
        invoice = {'status': 'FULFILLED'}
        months = 1

        if bag['chosen_period'] == 'QUARTER':
            months = 3

        elif bag['chosen_period'] == 'HALF':
            months = 6

        elif bag['chosen_period'] == 'YEAR':
            months = 12

        plan = {
            'time_of_life': None,
            'time_of_life_unit': None,
        }
        academy = {'available_as_saas': True}
        model = self.bc.database.create(bag=bag, invoice=invoice, cohort_set=1, plan=plan, academy=academy)

        # remove prints from mixer
        logging.Logger.info.call_args_list = []
        logging.Logger.error.call_args_list = []

        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [
            self.bc.format.to_dict(model.cohort),
        ])

        self.assertEqual(logging.Logger.info.call_args_list, [
            call('Starting build_subscription for bag 1'),
            call('Subscription was created with id 1'),
        ])
        self.assertEqual(logging.Logger.error.call_args_list, [])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [
            {
                **self.bc.format.to_dict(model.bag),
                'was_delivered': True,
            },
        ])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [
            self.bc.format.to_dict(model.invoice),
        ])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [
            subscription_item({
                'paid_at': model.invoice.paid_at,
                'valid_until': None,
                'selected_cohort_set_id': 1,
                'next_payment_at': model.invoice.paid_at + relativedelta(months=months),
            }),
        ])

        self.assertEqual(tasks.build_service_stock_scheduler_from_subscription.delay.call_args_list, [
            call(1),
        ])

    """
    🔽🔽🔽 With Bag, Invoice and EventTypeSet
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    @patch.object(timezone, 'now', MagicMock(return_value=UTC_NOW))
    @patch('breathecode.payments.tasks.build_service_stock_scheduler_from_subscription.delay', MagicMock())
    def test_subscription_was_created__bag_with_event_type_set(self):
        bag = {
            'status': 'PAID',
            'was_delivered': False,
            'chosen_period': random.choice(['MONTH', 'QUARTER', 'HALF', 'YEAR']),
        }
        invoice = {'status': 'FULFILLED'}
        months = 1

        if bag['chosen_period'] == 'QUARTER':
            months = 3

        elif bag['chosen_period'] == 'HALF':
            months = 6

        elif bag['chosen_period'] == 'YEAR':
            months = 12

        plan = {
            'time_of_life': None,
            'time_of_life_unit': None,
        }
        model = self.bc.database.create(bag=bag, invoice=invoice, event_type_set=1, plan=plan)

        # remove prints from mixer
        logging.Logger.info.call_args_list = []
        logging.Logger.error.call_args_list = []

        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [])

        self.assertEqual(logging.Logger.info.call_args_list, [
            call('Starting build_subscription for bag 1'),
            call('Subscription was created with id 1'),
        ])
        self.assertEqual(logging.Logger.error.call_args_list, [])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [
            {
                **self.bc.format.to_dict(model.bag),
                'was_delivered': True,
            },
        ])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [
            self.bc.format.to_dict(model.invoice),
        ])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [
            subscription_item({
                'paid_at': model.invoice.paid_at,
                'valid_until': None,
                'selected_event_type_set_id': 1,
                'next_payment_at': model.invoice.paid_at + relativedelta(months=months),
            }),
        ])

        self.assertEqual(tasks.build_service_stock_scheduler_from_subscription.delay.call_args_list, [
            call(1),
        ])

    """
    🔽🔽🔽 With Bag, Invoice and MentorshipServiceSet
    """

    @patch('logging.Logger.info', MagicMock())
    @patch('logging.Logger.error', MagicMock())
    @patch.object(timezone, 'now', MagicMock(return_value=UTC_NOW))
    @patch('breathecode.payments.tasks.build_service_stock_scheduler_from_subscription.delay', MagicMock())
    def test_subscription_was_created__bag_with_mentorship_service_set(self):
        bag = {
            'status': 'PAID',
            'was_delivered': False,
            'chosen_period': random.choice(['MONTH', 'QUARTER', 'HALF', 'YEAR']),
        }
        invoice = {'status': 'FULFILLED'}
        months = 1

        if bag['chosen_period'] == 'QUARTER':
            months = 3

        elif bag['chosen_period'] == 'HALF':
            months = 6

        elif bag['chosen_period'] == 'YEAR':
            months = 12

        plan = {
            'time_of_life': None,
            'time_of_life_unit': None,
        }
        model = self.bc.database.create(bag=bag, invoice=invoice, mentorship_service_set=1, plan=plan)

        # remove prints from mixer
        logging.Logger.info.call_args_list = []
        logging.Logger.error.call_args_list = []

        build_subscription.delay(1, 1)

        self.assertEqual(self.bc.database.list_of('admissions.Cohort'), [])

        self.assertEqual(logging.Logger.info.call_args_list, [
            call('Starting build_subscription for bag 1'),
            call('Subscription was created with id 1'),
        ])
        self.assertEqual(logging.Logger.error.call_args_list, [])

        self.assertEqual(self.bc.database.list_of('payments.Bag'), [
            {
                **self.bc.format.to_dict(model.bag),
                'was_delivered': True,
            },
        ])
        self.assertEqual(self.bc.database.list_of('payments.Invoice'), [
            self.bc.format.to_dict(model.invoice),
        ])
        self.assertEqual(self.bc.database.list_of('payments.Subscription'), [
            subscription_item({
                'paid_at': model.invoice.paid_at,
                'valid_until': None,
                'selected_mentorship_service_set_id': 1,
                'next_payment_at': model.invoice.paid_at + relativedelta(months=months),
            }),
        ])

        self.assertEqual(tasks.build_service_stock_scheduler_from_subscription.delay.call_args_list, [
            call(1),
        ])
