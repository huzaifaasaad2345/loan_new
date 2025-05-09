from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class LoanApplication(models.Model):
    _name = 'loan.application'
    _description = 'Loan Application'

    # Add fields 123
    name = fields.Char(string='Loan Reference', required=True, copy=False, readonly=True, default='New')
    customer_id = fields.Many2one('res.partner', string='Customer', required=True)
    customer_email=fields.Char(related='customer_id.email', string="Customer Email", readonly=True)
    loan_amount = fields.Float(string='Loan Amount', required=True)
    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.today)
    installment_ids = fields.One2many('loan.installment', 'loan_id')
    duration_months = fields.Integer(string='Loan Duration (Months)', required=True)
    # send_email=fields.Char()
    a = fields.Float(string="A")
    b = fields.Float(string="B")
    c = fields.Float(string="Compute A + B", compute="_compute_c", store=True, readonly=True)
    d = fields.Float(string="Onchange A + B", readonly=True)



    @api.depends('a', 'b')
    def _compute_c(self):
        for rec in self:
            rec.c = rec.a + rec.b
            print(f"Computed C: {rec.c}")

    @api.onchange('a', 'b')
    def _onchange_ab(self):
        for rec in self:
            rec.d = rec.a + rec.b
            print(f"Onchange D: {rec.d}")

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('loan.application') or 'New'
        loan = super().create(vals)
        print("customer email is:", loan.customer_email)
        loan._generate_installments()
        return loan

    def _generate_installments(self):
        installment_amount = self.loan_amount / self.duration_months
        for i in range(self.duration_months):
            due_date = self.start_date + relativedelta(months=i)
            self.env['loan.installment'].create({
                'loan_id': self.id,
                'installment_no': i + 1,
                'due_date': due_date,
                'amount': installment_amount,
                'description': f'Month {i + 1} Installment',
                'status': 'not_created',
            })
    # def action_send_email(self):
    #     for rec in self:
    #         template = self.env.ref('loan_manage.email_template_installment_due')
    #         template.send_mail(rec.id, force_send=True)
    #         if not template:
    #             raise UserError("Email template not found")

    def crone_send_due_installment_emails(self):
        print("in crone")
        reminder_date=fields.Date.today()+timedelta(days=5)

        due_soon_installments=self.env['loan.installment'].search([
            ('due_date', '=' , reminder_date),
            ('status', '=' , 'not_created')
        ])
        print("Reminder Date:", reminder_date)
        print("Found Installments:", due_soon_installments)
        template = self.env.ref('loan_manage.email_template_installment_due')
        if not template:
            raise UserError("Email template not found")

        for installment in due_soon_installments:
            template.send_mail(installment.id, force_send=True)
            print(f"Sent email for installment {installment.installment_no}.")


class LoanInstallment(models.Model):
    _name = 'loan.installment'
    _description = 'Loan Installment'

    loan_id = fields.Many2one('loan.application', string='Loan Application', ondelete='cascade')
    installment_no = fields.Integer(string='Installment #')
    due_date = fields.Date(string='Due Date')
    amount = fields.Float(string='Amount')
    description = fields.Char(string='Description')
    status = fields.Selection([
        ('not_created', 'Not Created'),
        ('created', 'Created'),
    ], string='Invoice Created Status', default='not_created')
    invoice_id = fields.Many2one('account.move', string="Invoice")
    invoice_status = fields.Selection(
        related='invoice_id.state',
        string='Invoice Status',
        readonly=True,
        store=True
    )

    def action_mark_as_paid(self):
        unpaid_previous_installments = self.env['loan.installment'].search([
            ('loan_id', '=', self.loan_id.id),
            ('due_date', '<', self.due_date),
            ('status', '=', 'not_created')
        ])

        for rec in self:
            if rec.status == 'created':
                raise UserError("Installment already created.")

        combined_installments = unpaid_previous_installments + self

        invoice_lines = []
        total_inst = 0
        for installment in combined_installments:
            invoice_lines.append((0, 0, {
                'name': installment.description,
                'quantity': 1,
                'price_unit': installment.amount,
                'account_id': self.env['account.account'].search([('account_type', '=', 'income')], limit=1).id,
            }))
            total_inst += installment.amount

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': rec.loan_id.customer_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': invoice_lines,
            'amount_total': total_inst,
        })

        for installment in combined_installments:
            installment.status = 'created'
            installment.invoice_id = invoice.id

