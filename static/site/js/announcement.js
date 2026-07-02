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
        W tym okresie, w bardzo pilnych sprawach, prosimy o kontakt za pośrednictwem formularza dostępnego na stronie
        <strong>www.kingabobinska.pl</strong>.
        Zapisy na wizyty będą możliwe wyłącznie przez stronę internetową.
        </p>
        `,
        en: `
        <p>
        The clinic will be <strong>closed from August 1 to September 3, 2026</strong>
        due to summer holidays.
        </p>

        <p>
        During this period, for urgent matters, please contact us using the contact form available at
        <strong>www.kingabobinska.pl</strong>.
        Appointments can be booked exclusively through the website.
        </p>
        `,

    },

    buttonBook: {

    pl: "Umów wizytę",

    en: "Book appointment"

    },

    button: {

        pl: "Zamknij",

        en: "Close"

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

    $("#announcementBookButton")
        .text(ANNOUNCEMENT.buttonBook[lang]);

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

// aktualizacja języka, jeśli popup jest otwarty
window.addEventListener("languageChanged", function () {

    const lang = localStorage.getItem("lang") || "pl";

    $("#announcementTitle")
        .text(ANNOUNCEMENT.title[lang]);

    $("#announcementBody")
        .html(ANNOUNCEMENT.message[lang]);

    $("#announcementBookButton")
        .text(ANNOUNCEMENT.buttonBook[lang]);

    $("#announcementButton")
        .text(ANNOUNCEMENT.button[lang]);

});