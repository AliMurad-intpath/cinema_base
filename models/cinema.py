import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def _tz_get(self):
    return [
        (tz, tz)
        for tz in sorted(pytz.all_timezones, key=lambda t: t if not t.startswith("Etc/") else "_")
    ]


class CinemaCinema(models.Model):
    _name = "cinema.cinema"
    _description = "Cinema Branch"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(help="Short internal code, e.g. BGD-01.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", store=True, string="Currency"
    )
    street = fields.Char()
    city = fields.Char()
    phone = fields.Char()
    email = fields.Char()
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    image = fields.Image(max_width=1280, max_height=1280)
    tz = fields.Selection(
        _tz_get,
        string="Time Zone",
        required=True,
        default=lambda self: self.env.user.tz or "UTC",
        help="Showtimes are stored in UTC and displayed in this time zone.",
    )
    business_day_cutoff_hour = fields.Integer(
        default=4,
        help="Showtimes starting before this local hour belong to the previous "
        "business day in reports (e.g. a 00:30 show counts for the day before).",
    )
    sales_cutoff_minutes = fields.Integer(
        default=15,
        help="Keep selling tickets this many minutes AFTER a showtime starts "
        "(late arrivals). Use a negative number to stop selling before the start.",
    )
    hall_ids = fields.One2many("cinema.hall", "cinema_id", string="Halls")
    hall_count = fields.Integer(compute="_compute_hall_count")

    @api.depends("hall_ids")
    def _compute_hall_count(self):
        for rec in self:
            rec.hall_count = len(rec.hall_ids)

    @api.constrains("business_day_cutoff_hour")
    def _check_cutoff_hour(self):
        for rec in self:
            if not 0 <= rec.business_day_cutoff_hour <= 12:
                raise ValidationError(
                    self.env._("The business day cut-off hour must be between 0 and 12.")
                )

    def action_open_halls(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Halls"),
            "res_model": "cinema.hall",
            "view_mode": "list,form",
            "domain": [("cinema_id", "=", self.id)],
            "context": {"default_cinema_id": self.id},
        }
