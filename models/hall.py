from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import ValidationError

SEAT_TYPES = [
    ("standard", "Standard"),
    ("vip", "VIP"),
    ("couple", "Couple"),
    ("wheelchair", "Wheelchair"),
]
HALL_FORMATS = [
    ("2d", "2D"),
    ("3d", "3D"),
    ("imax", "IMAX"),
    ("4dx", "4DX"),
    ("vip", "VIP Lounge"),
]
SEAT_TYPE_COLORS = {
    "standard": "#546e7a",
    "vip": "#b8860b",
    "couple": "#8e24aa",
    "wheelchair": "#1565c0",
}


def render_seat_grid(seats, color_of, tip_of):
    """Render a recordset of cinema.seat as an HTML seat map.

    ``color_of(seat)`` returns a CSS colour, ``tip_of(seat)`` the tooltip text.
    Aisles are detected from gaps in the x coordinate.
    """
    rows = defaultdict(list)
    for seat in seats.sorted(lambda s: (s.row_index, s.number)):
        rows[seat.row_label].append(seat)
    out = [
        '<div style="text-align:center;margin:4px 0 12px;padding:3px 0;'
        "background:#cfd8dc;color:#37474f;border-radius:50% 50% 0 0 / 100% 100% 0 0;"
        'font-size:11px;letter-spacing:4px;">SCREEN</div>'
    ]
    for label, row in rows.items():
        out.append(
            '<div style="white-space:nowrap;text-align:center;">'
            '<span style="display:inline-block;width:26px;font-size:11px;color:#78909c;">%s</span>'
            % escape(label)
        )
        prev = None
        for seat in row:
            gap = "margin-left:18px;" if prev is not None and (seat.pos_x - prev.pos_x) > 0.8 else ""
            border = "border:2px solid #ffd54f;" if seat.seat_type == "vip" else ""
            out.append(
                '<span title="%s" style="display:inline-block;width:26px;height:26px;'
                "line-height:22px;margin:2px;border-radius:6px;font-size:10px;"
                'text-align:center;color:#fff;box-sizing:border-box;background:%s;%s%s">%s</span>'
                % (escape(tip_of(seat)), color_of(seat), border, gap, seat.number)
            )
            prev = seat
        out.append("</div>")
    return Markup("".join(out))


class CinemaHall(models.Model):
    _name = "cinema.hall"
    _description = "Cinema Hall"
    _order = "cinema_id, name"

    name = fields.Char(required=True)
    cinema_id = fields.Many2one(
        "cinema.cinema", required=True, ondelete="restrict", index=True
    )
    hall_format = fields.Selection(HALL_FORMATS, string="Format", default="2d", required=True)
    active = fields.Boolean(default=True)
    seat_ids = fields.One2many("cinema.seat", "hall_id", string="Seats")
    seat_count = fields.Integer(
        compute="_compute_seat_count", store=True, string="Capacity"
    )
    currency_id = fields.Many2one(related="cinema_id.currency_id", string="Currency")
    vip_surcharge = fields.Monetary(help="Added to the showtime price for VIP seats.")
    couple_surcharge = fields.Monetary(help="Added to the showtime price for couple seats.")
    layout_preview = fields.Html(compute="_compute_layout_preview", sanitize=False)

    @api.depends("seat_ids.active")
    def _compute_seat_count(self):
        for rec in self:
            rec.seat_count = len(rec.seat_ids.filtered("active"))

    @api.depends("name", "cinema_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.cinema_id.name} / {rec.name}" if rec.cinema_id else (rec.name or "")
            )

    @api.depends("seat_ids", "seat_ids.seat_type", "seat_ids.pos_x")
    def _compute_layout_preview(self):
        labels = dict(SEAT_TYPES)
        for rec in self:
            seats = rec.seat_ids.filtered("active")
            if not seats:
                rec.layout_preview = False
                continue
            rec.layout_preview = render_seat_grid(
                seats,
                color_of=lambda s: SEAT_TYPE_COLORS.get(s.seat_type, "#546e7a"),
                tip_of=lambda s: f"{s.name} · {labels.get(s.seat_type, '')}",
            )

    def _check_can_reset_seats(self):
        """Hook: modules holding bookings override this to forbid destructive edits."""

    def action_generate_seats(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Generate Seats"),
            "res_model": "cinema.hall.generate.seats",
            "view_mode": "form",
            "target": "new",
            "context": {"default_hall_id": self.id},
        }

    def action_clear_seats(self):
        for hall in self:
            hall._check_can_reset_seats()
            hall.seat_ids.unlink()
        return True

    @api.model
    def _generate_demo_layouts(self):
        """Demo data helper: build seat layouts for the demo halls."""
        for xmlid, rows, per_row, aisle, vip_rows in (
            ("cinema_base.demo_hall_1", 8, 12, 6, 0),
            ("cinema_base.demo_hall_2", 5, 8, 4, 2),
        ):
            hall = self.env.ref(xmlid, raise_if_not_found=False)
            if hall and not hall.seat_ids:
                self.env["cinema.hall.generate.seats"].create(
                    {
                        "hall_id": hall.id,
                        "rows": rows,
                        "seats_per_row": per_row,
                        "aisle_after": aisle,
                        "vip_last_rows": vip_rows,
                    }
                ).action_generate()


class CinemaSeat(models.Model):
    _name = "cinema.seat"
    _description = "Cinema Seat"
    _order = "hall_id, row_index, number"

    hall_id = fields.Many2one(
        "cinema.hall", required=True, ondelete="cascade", index=True
    )
    row_label = fields.Char(required=True)
    row_index = fields.Integer(required=True, help="Row order, 1 = closest to the screen.")
    number = fields.Integer(required=True)
    name = fields.Char(compute="_compute_name", store=True)
    seat_type = fields.Selection(SEAT_TYPES, default="standard", required=True)
    pos_x = fields.Float(help="Metres from the hall centre line (left negative).")
    pos_y = fields.Float(help="Metres from the screen.")
    pos_z = fields.Float(help="Height above the first row, in metres.")
    active = fields.Boolean(default=True)

    @api.depends("row_label", "number")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.row_label or ''}{rec.number or ''}"

    @api.constrains("hall_id", "row_label", "number")
    def _check_unique_seat(self):
        for rec in self:
            clash = self.with_context(active_test=False).search_count(
                [
                    ("id", "!=", rec.id),
                    ("hall_id", "=", rec.hall_id.id),
                    ("row_label", "=", rec.row_label),
                    ("number", "=", rec.number),
                ]
            )
            if clash:
                raise ValidationError(
                    self.env._("Seat %s already exists in this hall.", rec.name)
                )
