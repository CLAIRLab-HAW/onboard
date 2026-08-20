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
export function classify({ status = null, error = null, pending = null } = {}) {
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

    if (error) {
        if (MISSING_RE.test(error)) {
            return {
                ...base,
                outline: true,
                missing: true,
                label: 'nicht angelegt',
                detail: 'Den Container gibt es auf diesem Rechner nicht. Einmal anlegen: '
                      + 'cd ~/offboard-lite && docker compose -f docker-compose.yml '
                      + '-f docker-compose.robot.yml up -d',
            };
        }
        return { ...base, color: 'red', label: 'Docker nicht erreichbar', detail: error };
    }

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
