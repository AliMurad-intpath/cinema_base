from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

SHOWTIME_STATES = [
    ("draft", "Draft"),
    ("published", "On Sale"),
    ("cancelled", "Cancelled"),
]


class CinemaShowtime(models.Model):
    _name = "cinema.showtime"
    _description = "Showtime"
    _order = "start_datetime, hall_id"

    movie_id = fields.Many2one("cinema.movie", required=True, ondelete="restrict", index=True)
    hall_id = fields.Many2one("cinema.hall", required=True, ondelete="restrict", index=True)
    cinema_id = fields.Many2one(related="hall_id.cinema_id", store=True, index=True)
    currency_id = fields.Many2one(related="cinema_id.currency_id", store=True)
    start_datetime = fields.Datetime(string="Start", required=True, index=True)
    buffer_minutes = fields.Integer(
        string="Buffer (min)", default=20, help="Ads, cleaning and entry time after the film."
    )
    end_datetime = fields.Datetime(string="End", compute="_compute_end_datetime", store=True, index=True)
    sales_close_datetime = fields.Datetime(compute="_compute_sales_close", store=True, index=True)
    business_date = fields.Date(compute="_compute_business_date", store=True, index=True)
    start_local = fields.Char(string="Local Start", compute="_compute_start_local")
    audio_language = fields.Char()
    subtitle_language = fields.Char()
    base_price = fields.Monetary(string="Base Price", required=True)
    state = fields.Selection(SHOWTIME_STATES, default="draft", required=True, index=True)
    is_sellable = fields.Boolean(compute="_compute_is_sellable")

    # ------------------------------------------------------------------ computes
    @api.depends("start_datetime", "buffer_minutes", "movie_id.duration_minutes")
    def _compute_end_datetime(self):
        for rec in self:
            if rec.start_datetime:
                minutes = (rec.movie_id.duration_minutes or 0) + (rec.buffer_minutes or 0)
                rec.end_datetime = rec.start_datetime + timedelta(minutes=minutes)
            else:
                rec.end_datetime = False

    @api.depends("start_datetime", "cinema_id.sales_cutoff_minutes")
    def _compute_sales_close(self):
        for rec in self:
            if rec.start_datetime:
                rec.sales_close_datetime = rec.start_datetime + timedelta(
                    minutes=rec.cinema_id.sales_cutoff_minutes or 0
                )
            else:
                rec.sales_close_datetime = False

    @api.depends("start_datetime", "cinema_id.tz", "cinema_id.business_day_cutoff_hour")
    def _compute_business_date(self):
        for rec in self:
            if not rec.start_datetime:
                rec.business_date = False
                continue
            tz = pytz.timezone(rec.cinema_id.tz or "UTC")
            local = pytz.utc.localize(rec.start_datetime).astimezone(tz)
            local -= timedelta(hours=rec.cinema_id.business_day_cutoff_hour or 0)
            rec.business_date = local.date()

    @api.depends("start_datetime", "cinema_id.tz")
    def _compute_start_local(self):
        for rec in self:
            if rec.start_datetime and rec.cinema_id:
                tz = pytz.timezone(rec.cinema_id.tz or "UTC")
                local = pytz.utc.localize(rec.start_datetime).astimezone(tz)
                rec.start_local = local.strftime("%Y-%m-%d %H:%M")
            else:
                rec.start_local = False

    @api.depends("state", "sales_close_datetime")
    def _compute_is_sellable(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_sellable = bool(
                rec.state == "published"
                and rec.sales_close_datetime
                and rec.sales_close_datetime >= now
            )

    @api.depends("movie_id.name", "hall_id.name", "start_datetime", "cinema_id.tz")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " · ".join(
                part
                for part in (rec.movie_id.name, rec.hall_id.name, rec.start_local)
                if part
            )

    # --------------------------------------------------------------- constraints
    @api.constrains("hall_id", "start_datetime", "end_datetime", "state")
    def _check_hall_overlap(self):
        for rec in self.filtered(lambda r: r.state != "cancelled" and r.start_datetime):
            clash = self.search(
                [
                    ("id", "!=", rec.id),
                    ("hall_id", "=", rec.hall_id.id),
                    ("state", "!=", "cancelled"),
                    ("start_datetime", "<", rec.end_datetime),
                    ("end_datetime", ">", rec.start_datetime),
                ],
                limit=1,
            )
            if clash:
                raise ValidationError(
                    self.env._(
                        "%(hall)s is already used by '%(other)s' at that time.",
                        hall=rec.hall_id.display_name,
                        other=clash.display_name,
                    )
                )

    @api.constrains("base_price")
    def _check_price(self):
        for rec in self:
            if rec.base_price < 0:
                raise ValidationError(self.env._("The price cannot be negative."))

    # ------------------------------------------------------------------- helpers
    @api.model
    def _sellable_domain(self, cinema_id=None, business_date=None, movie_id=None):
        """Domain of showtimes that can currently be sold."""
        domain = [
            ("state", "=", "published"),
            ("sales_close_datetime", ">=", fields.Datetime.now()),
        ]
        if cinema_id:
            domain.append(("cinema_id", "=", cinema_id))
        if business_date:
            domain.append(("business_date", "=", business_date))
        if movie_id:
            domain.append(("movie_id", "=", movie_id))
        return domain

    # ------------------------------------------------------------------- actions
    def action_publish(self):
        for rec in self:
            if rec.state == "cancelled":
                raise UserError(self.env._("A cancelled showtime cannot be published."))
            if not rec.hall_id.seat_count:
                raise UserError(
                    self.env._("%s has no seats. Generate the seat layout first.", rec.hall_id.display_name)
                )
        self.write({"state": "published"})

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    @api.model
    def _generate_demo_showtimes(self):
        """Demo data helper: schedule the demo movies for the next few days."""
        plan = (
            ("cinema_base.demo_movie_1", "cinema_base.demo_hall_1", "13:00, 16:00, 19:00, 22:00", 8000),
            ("cinema_base.demo_movie_2", "cinema_base.demo_hall_2", "14:00, 17:00, 20:00", 12000),
        )
        today = fields.Date.today()
        for movie_xmlid, hall_xmlid, slots, price in plan:
            movie = self.env.ref(movie_xmlid, raise_if_not_found=False)
            hall = self.env.ref(hall_xmlid, raise_if_not_found=False)
            if not (movie and hall and hall.seat_count):
                continue
            self.env["cinema.showtime.generate"].create(
                {
                    "movie_id": movie.id,
                    "hall_ids": [(6, 0, hall.ids)],
                    "date_from": today,
                    "date_to": today + timedelta(days=3),
                    "time_slots": slots,
                    "base_price": price,
                    "publish": True,
                }
            ).action_generate()
