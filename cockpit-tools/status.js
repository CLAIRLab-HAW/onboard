// Zustandsabbildung fuer die Statuskugel.
//
// Bewusst eine reine Funktion ohne DOM, ohne cockpit.js und ohne Docker: sie
// ist die einzige Stelle mit Entscheidungslogik und laesst sich deshalb hier
// am Schreibtisch pruefen (test/status.test.mjs, `node --test test/`), waehrend
// der Rest der Seite nur noch Knoepfe und Text ist.
//
// Farbabsprache (bewusst nicht die uebliche Ampel):
//   gruen  = laeuft
//   grau   = gestoppt -- das ist der NORMALFALL, kein Fehler
//   gelb   = Uebergang (Start/Stopp unterwegs, restarting)
//   rot    = Fehler: Docker antwortet nicht, oder der Container ist defekt
// Waere "gestoppt" rot, leuchtete die Kugel die meiste Zeit alarmierend, ohne
// dass irgendetwas kaputt ist -- und ein echter Fehler ginge darin unter.

const MISSING_RE = /no such (object|container)/i;

/**
 * @param {object} state
 * @param {string} [state.status]  Docker-Zustand aus `docker inspect -f '{{.State.Status}}'`
 * @param {string} [state.error]   Fehlertext des letzten Docker-Aufrufs
 * @param {'start'|'stop'} [state.pending] laufendes Kommando
 * @returns {{color:string,label:string,detail:string,pulse:boolean,
 *            outline:boolean,missing:boolean,canStart:boolean,canStop:boolean}}
 */
export function classify({ status = null, error = null, pending = null, missing = false } = {}) {
    const base = {
        color: 'grey',
        label: '',
        detail: '',
        pulse: false,
        outline: false,
        missing: false,
        canStart: false,
        canStop: false,
    };

    // Ein laufendes Kommando schlaegt alles andere: waehrend `docker start`
    // arbeitet, meldet inspect noch minutenlang den alten Zustand.
    if (pending === 'start')
        return { ...base, color: 'yellow', pulse: true, label: 'startet…' };
    if (pending === 'stop')
        return { ...base, color: 'yellow', pulse: true, label: 'stoppt…' };

    if (missing || (error && MISSING_RE.test(error))) {
        return {
            ...base,
            outline: true,
            missing: true,
            label: 'nicht angelegt',
            // Kein geratener Pfad: die Seite kennt den Ablageort des
            // Compose-Projekts nicht, und ein falsches "cd" schickt den
            // Leser genau in die Irre, aus der er kommt.
            detail: 'Auf diesem Rechner gibt es keinen Container aus dem Image '
                  + 'husky-offboard-lite (compose-Dienst moveit-rviz). Einmal anlegen, '
                  + 'im Verzeichnis des Compose-Projekts: docker compose '
                  + '-f docker-compose.yml -f docker-compose.robot.yml up -d',
        };
    }

    if (error)
        return { ...base, color: 'red', label: 'Docker nicht erreichbar', detail: error };

    switch (status) {
    case null:
        return { ...base, label: 'wird geprüft…' };
    case 'running':
        return { ...base, color: 'green', label: 'läuft', canStop: true };
    case 'exited':
    case 'created':
        return { ...base, label: 'gestoppt', canStart: true };
    case 'paused':
        // `docker start` scheitert an einem pausierten Container, `docker stop`
        // nicht -- deshalb hier nur der Stopp-Knopf.
        return { ...base, label: 'pausiert', canStop: true };
    case 'restarting':
        return { ...base, color: 'yellow', pulse: true, label: 'startet neu…' };
    case 'dead':
        return {
            ...base,
            color: 'red',
            label: 'defekt (dead)',
            detail: 'Docker bekommt den Container nicht mehr aufgeraeumt. '
                  + 'Hilft nur noch: docker rm -f und neu anlegen.',
            canStop: true,
        };
    default:
        // Lieber den unbekannten Zustand woertlich zeigen als ihn zu raten.
        return { ...base, label: status };
    }
}

/**
 * Ob jetzt abgefragt werden soll.
 *
 * Im Hintergrundtab wird gespart -- die Seite bleibt in Cockpit geladen, auch
 * wenn man laengst woanders ist, und jede Abfrage ist ein Docker-Aufruf mit
 * Root-Rechten. Die ERSTE Abfrage laeuft aber immer: eine Seite, die nie im
 * Vordergrund war (Cockpit im Hintergrundtab geoeffnet, oder ein Browser, der
 * das Rahmenfenster als verborgen meldet), stuende sonst fuer immer auf
 * "wird geprueft…".
 *
 * @param {{hidden:boolean, everFetched:boolean}} ctx
 * @returns {boolean}
 */
export function shouldPoll({ hidden = false, everFetched = false } = {}) {
    return !hidden || !everFetched;
}

// Adressen, die zwar in der Adresszeile stehen koennen, als VNC-Ziel aber
// auf den falschen Rechner zeigen (Cockpit direkt auf dem Roboter geoeffnet,
// oder durch einen SSH-Tunnel).
const LOCAL_HOSTS = ['', 'localhost', '127.0.0.1', '::1'];

/**
 * Unter welcher Adresse der Betrachter den VNC-Port dieses Rechners erreicht.
 *
 * @param {{transportHost?:string, locationHost?:string, fallback:string}} ctx
 *   transportHost = cockpit.transport.host (ueber einen Sprungrechner der
 *   Zielrechner, sonst "localhost"), locationHost = window.location.hostname.
 * @returns {string}
 */
export function resolveHost({ transportHost = null, locationHost = '', fallback = '' } = {}) {
    const via = (transportHost || '').replace(/^.*@/, '');
    if (via && !LOCAL_HOSTS.includes(via))
        return via;
    if (locationHost && !LOCAL_HOSTS.includes(locationHost))
        return locationHost;
    return fallback;
}

// --- Den Container finden, statt seinen Namen zu raten --------------------
//
// Der Name eines compose-Containers ist <projekt>-<dienst>-<n>, und das
// Projekt heisst per Vorgabe wie das VERZEICHNIS. Ein fest verdrahtetes
// "offboard-lite-moveit-rviz-1" ist damit eine Wette auf den Ablageort --
// verloren am 2026-08-20, als die Seite auf dem Roboter "nicht angelegt"
// meldete und dazu ein falsches Verzeichnis nannte.
//
// Erkannt wird stattdessen an zwei Merkmalen, die den Ablageort nicht kennen:
// dem compose-Dienst (im Compose dieses Images heisst er moveit-rviz) und dem
// Image-Namen.

const COMPOSE_SERVICE = 'moveit-rviz';
const IMAGE_HINT = 'offboard-lite';

/**
 * Zerlegt die Ausgabe von
 * `docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}'`.
 *
 * @param {string} text
 * @returns {Array<{name:string,image:string,state:string,service:string}>}
 */
export function parseContainers(text) {
    return (text || '')
            .split('\n')
            .map(line => line.trimEnd())
            .filter(line => line.trim() !== '')
            .map(line => {
                const [name = '', image = '', state = '', service = ''] = line.split('\t');
                return {
                    name: name.trim(),
                    image: image.trim(),
                    state: state.trim(),
                    service: service.trim(),
                };
            })
            .filter(row => row.name !== '');
}

/**
 * Sucht den Offboard-Lite-Container heraus.
 *
 * @param {ReturnType<typeof parseContainers>} rows
 * @returns {{container: object|null, others: Array<object>}}
 *   `others` sind weitere Treffer -- mehr als einer ist kein Fehler (ein alter
 *   Container aus einem umbenannten Projekt bleibt liegen), aber die Seite
 *   sagt dann, welchen sie bedient.
 */
export function pickContainer(rows, { service = COMPOSE_SERVICE, imageHint = IMAGE_HINT } = {}) {
    const hits = (rows || []).filter(r =>
        r.service === service || r.image.includes(imageHint));

    if (hits.length === 0)
        return { container: null, others: [] };

    // Laufende zuerst: wer zwei Container hat, meint den, der arbeitet.
    const running = hits.filter(r => r.state === 'running');
    const chosen = running.length > 0 ? running[0] : hits[0];

    return { container: chosen, others: hits.filter(r => r !== chosen) };
}

// --- Warum der VNC-Port von aussen nicht erreichbar ist -------------------
//
// Am 2026-08-20 an a200-0553 gemessen: 6080 offen, 5900 keine Antwort. Zwei
// Ursachen erzeugen dieses Bild, und beide entstehen beim ANLEGEN des
// Containers -- ein `docker start` kann sie nicht heilen, weil es den
// Container mit genau seiner alten Konfiguration hochfaehrt. Die Seite sagt
// deshalb, welche der beiden vorliegt, statt den Leser raten zu lassen.

/**
 * Zerlegt die Ausgabe von
 * `docker inspect -f '{{.HostConfig.NetworkMode}}{{"\n"}}{{range .Config.Env}}{{println .}}{{end}}'`.
 *
 * @param {string} text
 * @returns {{networkMode:string, env:string[]}|null}
 */
export function parseInspect(text) {
    const lines = (text || '').split('\n').map(l => l.trim()).filter(l => l !== '');
    if (lines.length === 0)
        return null;
    return { networkMode: lines[0], env: lines.slice(1) };
}

/**
 * @param {{networkMode:string, env:string[]}|null} info
 * @returns {Array<{code:string, text:string}>} leer, wenn alles passt.
 *   Der Code ist dazu da, andere Stellen der Seite stumm zu schalten: solange
 *   "no-password" gilt, darf daneben nicht stehen, der Viewer frage nach einem.
 */
export function diagnoseVnc(info, { probe = null } = {}) {
    if (!info)
        return [];

    const notes = [];

    // Von INNEN gemessen: lauscht ueberhaupt jemand auf 5900? Das trennt einen
    // toten Desktop von einem, der nur nach aussen nicht erreichbar ist -- von
    // aussen sehen beide gleich aus (6080 offen, 5900 stumm). Steht diese
    // Meldung, sind die beiden Ursachen darunter zweitrangig.
    if (probe === 'down') {
        notes.push({
            code: 'desktop-down',
            text: 'Im Container lauscht niemand auf Port 5900 — der Desktop ist beim Neustart '
                + 'nicht hochgekommen. Bei Images ohne den Lock-Fix vom 2026-08-20 passiert das '
                + 'nach jedem Stop+Start: Xvfb findet sein altes Lock in /tmp vor und bricht ab, '
                + 'x11vnc stirbt mit. Sofort geholfen ist mit '
                + 'docker compose ... up -d --force-recreate (frisches /tmp); dauerhaft mit '
                + 'einem neu gebauten Base-Image.',
        });
    }

    // Ohne Passwort bietet x11vnc nur Security-Typ "None" an -- und bindet
    // dann an 127.0.0.1 statt 0.0.0.0. noVNC auf 6080 merkt davon nichts,
    // weil websockify containerintern verbindet. Genau daher der Eindruck
    // "der Container laeuft doch".
    const pw = info.env.find(e => e.startsWith('VNC_PASSWORD='));
    if (!pw || pw.slice('VNC_PASSWORD='.length).trim() === '') {
        notes.push({
            code: 'no-password',
            text: 'Dieser Container läuft ohne VNC_PASSWORD — x11vnc lauscht dann nur auf '
                + 'localhost, ein Viewer von außen bekommt keine Verbindung (noVNC auf 6080 '
                + 'geht trotzdem). Ein Neustart ändert das nicht: den Container mit gesetztem '
                + 'VNC_PASSWORD neu anlegen.',
        });
    }

    // Ohne den robot-Override laeuft der Container im Bridge-Netz, und das
    // Port-Mapping bindet 5900 an 127.0.0.1 des Roboters.
    if (info.networkMode && info.networkMode !== 'host') {
        notes.push({
            code: 'bridge-network',
            text: 'Dieser Container läuft im Bridge-Netz (' + info.networkMode + '), nicht im '
                + 'Netz des Roboters — Port 5900 liegt dann nur auf dessen 127.0.0.1. Mit '
                + '-f docker-compose.robot.yml neu anlegen.',
        });
    }

    return notes;
}

/**
 * @param {Array<{code:string}>} notes
 * @param {string} code
 * @returns {boolean}
 */
export function hasCode(notes, code) {
    return (notes || []).some(n => n.code === code);
}

/**
 * Glaettet die 5900-Messung: ein einzelnes "down" ist kein Befund.
 *
 * Nach `docker start` steht der Container sofort auf `running`, waehrend Xvfb,
 * fluxbox und x11vnc noch hochkommen -- wer da schon misst, meldet die
 * Anlaufzeit als Defekt. "up" gilt dagegen sofort: wer antwortet, lebt.
 *
 * @param {{streak:number}|null} previous voriger Stand
 * @param {'up'|'down'|null} probe Messung ('null' = nicht messbar)
 * @param {{needed?:number}} [opts] wie oft "down" hintereinander noetig ist
 * @returns {{streak:number, value:'up'|'down'|null}}
 */
export function settleProbe(previous, probe, { needed = 3 } = {}) {
    const streak = previous ? previous.streak : 0;

    if (probe === 'up')
        return { streak: 0, value: 'up' };

    // Nicht messbar (kein bash im Container, exec verweigert): nichts
    // behaupten, aber auch nichts vergessen.
    if (probe !== 'down')
        return { streak, value: null };

    const next = streak + 1;
    return { streak: next, value: next >= needed ? 'down' : null };
}
