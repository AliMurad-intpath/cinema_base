from odoo import api, fields, models

MOVIE_STATES = [
    ("draft", "Draft"),
    ("coming_soon", "Coming Soon"),
    ("now_showing", "Now Showing"),
    ("ended", "Ended"),
]


class CinemaGenre(models.Model):
    _name = "cinema.genre"
    _description = "Movie Genre"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()


class CinemaMovie(models.Model):
    _name = "cinema.movie"
    _description = "Movie"
    _order = "state, release_date desc, name"

    name = fields.Char(string="Title", required=True, translate=True)
    original_title = fields.Char()
    synopsis = fields.Text(translate=True)
    poster = fields.Image(max_width=1024, max_height=1536)
    poster_256 = fields.Image(
        related="poster", max_width=256, max_height=384, store=True
    )
    banner = fields.Image(max_width=1920, max_height=1080)
    trailer_url = fields.Char()
    duration_minutes = fields.Integer(string="Duration (min)", required=True, default=120)
    release_date = fields.Date()
    original_language = fields.Char()
    rating = fields.Selection(
        [("g", "G"), ("pg", "PG"), ("pg13", "PG-13"), ("r", "R"), ("18", "18+")],
        string="Age Rating",
    )
    genre_ids = fields.Many2many("cinema.genre", string="Genres")
    state = fields.Selection(MOVIE_STATES, default="draft", required=True, index=True)
    active = fields.Boolean(default=True)
    showtime_ids = fields.One2many("cinema.showtime", "movie_id")
    upcoming_showtime_count = fields.Integer(compute="_compute_upcoming_showtime_count")

    def _compute_upcoming_showtime_count(self):
        now = fields.Datetime.now()
        groups = self.env["cinema.showtime"]._read_group(
            [("movie_id", "in", self.ids), ("state", "=", "published"), ("end_datetime", ">=", now)],
            groupby=["movie_id"],
            aggregates=["__count"],
        )
        counts = {movie.id: count for movie, count in groups}
        for rec in self:
            rec.upcoming_showtime_count = counts.get(rec.id, 0)

    def action_set_coming_soon(self):
        self.write({"state": "coming_soon"})

    def action_set_now_showing(self):
        self.write({"state": "now_showing"})

    def action_set_ended(self):
        self.write({"state": "ended"})

    def action_open_showtimes(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Showtimes"),
            "res_model": "cinema.showtime",
            "view_mode": "list,calendar,form",
            "domain": [("movie_id", "=", self.id)],
            "context": {"default_movie_id": self.id},
        }

    @api.model
    def _cron_update_states(self):
        """Keep the movie lifecycle in sync with release dates and the schedule.

        * release date in the future            -> coming soon
        * has published upcoming showtimes      -> now showing
        * was showing and nothing is left       -> ended
        Draft and manually ended movies are left untouched.
        """
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        Showtime = self.env["cinema.showtime"]
        for movie in self.search([("state", "in", ("coming_soon", "now_showing"))]):
            upcoming = Showtime.search_count(
                [
                    ("movie_id", "=", movie.id),
                    ("state", "=", "published"),
                    ("end_datetime", ">=", now),
                ],
                limit=1,
            )
            if movie.release_date and movie.release_date > today:
                new_state = "coming_soon"
            elif upcoming:
                new_state = "now_showing"
            elif movie.state == "now_showing":
                new_state = "ended"
            else:
                new_state = movie.state
            if new_state != movie.state:
                movie.state = new_state
        return True
