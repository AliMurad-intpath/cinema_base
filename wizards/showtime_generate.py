from datetime import datetime, timedelta

import pytz

from odoo import fields, models
from odoo.exceptions import UserError


class ShowtimeGenerate(models.TransientModel):
    _name = "cinema.showtime.generate"
    _description = "Generate Showtimes in Bulk"

    movie_id = fields.Many2one("cinema.movie", required=True)
    hall_ids = fields.Many2many("cinema.hall", string="Halls", required=True)
    date_from = fields.Date(required=True, default=fields.Date.today)
    date_to = fields.Date(required=True, default=fields.Date.today)
    time_slots = fields.Char(
        required=True,
        default="13:00, 16:00, 19:00, 22:00",
        help="Local start times (24h, HH:MM), separated by commas.",
    )
    buffer_minutes = fields.Integer(default=20)
    base_price = fields.Float(required=True)
    audio_language = fields.Char()
    subtitle_language = fields.Char()
    publish = fields.Boolean(string="Put on Sale Immediately", default=False)

    def _parse_slots(self):
        slots = []
        for raw in (self.time_slots or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed = datetime.strptime(raw, "%H:%M").time()
            except ValueError:
                raise UserError(self.env._("'%s' is not a valid time. Use HH:MM.", raw))
            slots.append(parsed)
        if not slots:
            raise UserError(self.env._("Enter at least one start time."))
        return slots

    def action_generate(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(self.env._("The end date is before the start date."))
        if (self.date_to - self.date_from).days > 92:
            raise UserError(self.env._("Please generate at most about three months at a time."))
        slots = self._parse_slots()
        Showtime = self.env["cinema.showtime"]
        duration = timedelta(minutes=(self.movie_id.duration_minutes or 0) + self.buffer_minutes)
        created = Showtime
        skipped = 0
        day = self.date_from
        while day <= self.date_to:
            for hall in self.hall_ids:
                tz = pytz.timezone(hall.cinema_id.tz or "UTC")
                for slot in slots:
                    local = tz.localize(datetime.combine(day, slot))
                    start = local.astimezone(pytz.utc).replace(tzinfo=None)
                    clash = Showtime.search_count(
                        [
                            ("hall_id", "=", hall.id),
                            ("state", "!=", "cancelled"),
                            ("start_datetime", "<", start + duration),
                            ("end_datetime", ">", start),
                        ],
                        limit=1,
                    )
                    if clash:
                        skipped += 1
                        continue
                    created |= Showtime.create(
                        {
                            "movie_id": self.movie_id.id,
                            "hall_id": hall.id,
                            "start_datetime": start,
                            "buffer_minutes": self.buffer_minutes,
                            "base_price": self.base_price,
                            "audio_language": self.audio_language,
                            "subtitle_language": self.subtitle_language,
                            "state": "published" if self.publish and hall.seat_count else "draft",
                        }
                    )
            day += timedelta(days=1)
        if not created:
            raise UserError(
                self.env._("Nothing was created: all %s slots overlap existing showtimes.", skipped)
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Generated Showtimes (%s skipped for overlaps)", skipped),
            "res_model": "cinema.showtime",
            "view_mode": "list,calendar,form",
            "domain": [("id", "in", created.ids)],
        }
