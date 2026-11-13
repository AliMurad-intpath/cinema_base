from odoo import fields, models
from odoo.exceptions import UserError

AISLE_GAP = 0.9  # extra metres inserted at an aisle


def row_label(index):
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    label, n = "", index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        label = chr(65 + rem) + label
    return label


class HallGenerateSeats(models.TransientModel):
    _name = "cinema.hall.generate.seats"
    _description = "Generate Hall Seat Layout"

    hall_id = fields.Many2one("cinema.hall", required=True, ondelete="cascade")
    rows = fields.Integer(default=10, required=True)
    seats_per_row = fields.Integer(default=12, required=True)
    aisle_after = fields.Integer(
        string="Aisle After Seat",
        default=0,
        help="Insert a vertical aisle after this seat number. 0 = no aisle.",
    )
    vip_last_rows = fields.Integer(
        string="VIP Rows (from the back)", default=0,
        help="Number of rows at the back that are created as VIP seats.",
    )
    replace_existing = fields.Boolean(
        string="Replace Existing Seats",
        help="Delete the current seats first. Not possible once tickets were sold.",
    )
    first_row_distance = fields.Float(string="Distance Screen → Row A (m)", default=4.0)
    row_spacing = fields.Float(string="Row Spacing (m)", default=1.0)
    row_rise = fields.Float(string="Rise per Row (m)", default=0.25)
    seat_spacing = fields.Float(string="Seat Spacing (m)", default=0.55)

    def action_generate(self):
        self.ensure_one()
        hall = self.hall_id
        if self.rows < 1 or self.seats_per_row < 1:
            raise UserError(self.env._("Rows and seats per row must be at least 1."))
        if hall.seat_ids:
            if not self.replace_existing:
                raise UserError(
                    self.env._("This hall already has seats. Tick 'Replace Existing Seats' to rebuild it.")
                )
            hall._check_can_reset_seats()
            hall.seat_ids.unlink()
        has_aisle = 0 < self.aisle_after < self.seats_per_row
        width = (self.seats_per_row - 1) * self.seat_spacing + (AISLE_GAP if has_aisle else 0.0)
        vals = []
        for r in range(self.rows):
            seat_type = "vip" if r >= self.rows - max(self.vip_last_rows, 0) else "standard"
            for n in range(1, self.seats_per_row + 1):
                x = (n - 1) * self.seat_spacing - width / 2
                if has_aisle and n > self.aisle_after:
                    x += AISLE_GAP
                vals.append(
                    {
                        "hall_id": hall.id,
                        "row_label": row_label(r),
                        "row_index": r + 1,
                        "number": n,
                        "seat_type": seat_type,
                        "pos_x": round(x, 3),
                        "pos_y": round(self.first_row_distance + r * self.row_spacing, 3),
                        "pos_z": round(r * self.row_rise, 3),
                    }
                )
        self.env["cinema.seat"].create(vals)
        return {"type": "ir.actions.act_window_close"}
