// ==========================================================
// KONFIGURACJA
// ==========================================================

const ANNOUNCEMENT = {

    enabled: true,

    showOnce: false,

    version: 1,

    startDate: "2026-07-01",

    endDate: "2026-07-31",

    title: {

        pl: "📢 Ważna informacja",

        en: "📢 Important information"

    },

    message: {

        pl: `
<p>
Gabinet będzie <strong>nieczynny od 1 sierpnia do 3 września 2026 r.</strong>
z powodu urlopu.
</p>

<p>
Jeżeli planują Państwo wizytę przed tym terminem,
zachęcamy do wcześniejszej rezerwacji dostępnych terminów
jeszcze w <strong>lipcu</strong>.
</p>

<p>
Rejestracja wizyt zostanie wznowiona
od <strong>4 września 2026 r.</strong>
</p>
`,

        en: `
<p>
The clinic will be closed
<strong>from August 1 to September 3, 2026</strong>
due to summer holidays.
</p>

<p>
If you are planning an appointment before this period,
we encourage you to book your visit
during <strong>July</strong>.
</p>

<p>
Appointments will resume on
<strong>September 4, 2026.</strong>
</p>
`

    },

    button: {

        pl: "Rozumiem",

        en: "OK"

    }

};


// ==========================================================
// WYŚWIETLENIE
// ==========================================================

function showAnnouncement() {

    if (!ANNOUNCEMENT.enabled)
        return;

    const today = new Date();

    if (ANNOUNCEMENT.startDate) {

        const start = new Date(ANNOUNCEMENT.startDate);

        if (today < start)
            return;
    }

    if (ANNOUNCEMENT.endDate) {

        const end = new Date(ANNOUNCEMENT.endDate);
        end.setHours(23,59,59,999);

        if (today > end)
            return;
    }

    const storageKey =
        "announcement_seen_" + ANNOUNCEMENT.version;

    if (
        ANNOUNCEMENT.showOnce &&
        localStorage.getItem(storageKey)
    ) {
        return;
    }

    const lang = localStorage.getItem("lang") || "pl";

    $("#announcementTitle")
        .text(ANNOUNCEMENT.title[lang]);

    $("#announcementBody")
        .html(ANNOUNCEMENT.message[lang]);

    $("#announcementButton")
        .text(ANNOUNCEMENT.button[lang]);

    $("#announcementModal")
        .modal({
            backdrop: "static",
            keyboard: true
        });

    $("#announcementModal")
        .modal("show");

    $("#announcementModal")
        .one("hidden.bs.modal", function () {

            if (ANNOUNCEMENT.showOnce) {

                localStorage.setItem(
                    storageKey,
                    "1"
                );

            }

        });

}

$(function () {

    showAnnouncement();

});