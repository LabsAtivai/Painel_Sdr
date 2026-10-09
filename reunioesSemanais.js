const { google } = require('googleapis');

const SPREADSHEET_ID = '15XBHreEoGaWl8-ctys_0Jfj1OYLWd7Koe3iN40z6Z6M';
const CREDENTIALS_SHEET_NAME = 'Credentials';
const OUTPUT_SHEET_NAME = 'Reunioes do Dia Seguinte';
const SERVICE_ACCOUNT_FILE = './service-account-credentials.json';

const EMAIL_MAPPING = {
  'sdr7.ativa@gmail.com': 'Esthela', 
  'sdr0.ativaai@gmail.com': 'Andrade', 
  'sdr6.ativa@gmail.com': 'Leo',  
  'sdr3.1.ativa@gmail.com': 'Nicole', 
  'sdr2.ativaai@gmail.com': 'Domingues', 
  'sdr1.ativaai@gmail.com': 'Julia', 
  'sdr9.ativa@gmail.com': 'Tura',  
  'sdr4ativa@gmail.com':'Taina',

};

function pad(n) { return String(n).padStart(2, '0'); }

function formatDateBR(dateString) {
  const d = new Date(dateString);
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatDateOnlyBR(date) {
  const d = new Date(date);
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
}

function normalizeText(str = '') {
  return str.toString()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().trim();
}

// ✅ só conta se tiver "reuniao entre" OU "proposta entre"
function isRelevantEvent(summary = '') {
  const s = normalizeText(summary);
  return /\b(reuniao|reunioes|proposta|propostas)\s+entre\b/.test(s);
}

// ✅ proposta se tiver "proposta entre"
function isProposal(summary = '') {
  const s = normalizeText(summary);
  return /\bproposta\s+entre\b/.test(s);
}

// Semana vigente (segunda a domingo)
function getCurrentWeekRange() {
  const now = new Date();
  const dayOfWeek = now.getDay();
  const monday = new Date(now);
  monday.setDate(now.getDate() - (dayOfWeek === 0 ? 6 : dayOfWeek - 1));
  monday.setHours(0, 0, 0, 0);

  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  sunday.setHours(23, 59, 59, 999);

  return { monday, sunday };
}

// chave do dia YYYY-MM-DD
function dayKey(dateString) {
  const d = new Date(dateString);
  const y = d.getFullYear();
  const m = pad(d.getMonth() + 1);
  const da = pad(d.getDate());
  return `${y}-${m}-${da}`;
}
function dayKeyToBR(key) {
  const [y, m, d] = key.split('-');
  return `${d}/${m}/${y}`;
}

// ---- Sheets helpers
async function authenticateServiceAccount() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ['https://www.googleapis.com/auth/spreadsheets']
  });
  return auth.getClient();
}

async function readCredentialsFromSheet(auth) {
  const sheets = google.sheets({ version: 'v4', auth });
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${CREDENTIALS_SHEET_NAME}!A:D`
  });

  const rows = response.data.values || [];
  if (rows.length <= 1) return [];

  return rows.slice(1).map(row => ({
    user_email: (row[0] || '').trim(),
    refresh_token: (row[1] || '').trim(),
    client_id: (row[2] || '').trim(),
    client_secret: (row[3] || '').trim()
  })).filter(c => c.user_email && c.refresh_token && c.client_id && c.client_secret);
}

async function writeToSheetClean(sheets, data) {
  const spreadsheet = await sheets.spreadsheets.get({ spreadsheetId: SPREADSHEET_ID });
  const sheet = spreadsheet.data.sheets.find(s => s.properties.title === OUTPUT_SHEET_NAME);

  const header = ['SDR','Email do Convidado','Título da Reunião','Início','Fim','Descrição','Local'];

  if (!sheet) {
    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: SPREADSHEET_ID,
      resource: { requests: [{ addSheet: { properties: { title: OUTPUT_SHEET_NAME } } }] }
    });

    await sheets.spreadsheets.values.update({
      spreadsheetId: SPREADSHEET_ID,
      range: `${OUTPUT_SHEET_NAME}!A1:G1`,
      valueInputOption: 'RAW',
      resource: { values: [header] }
    });
  } else {
    const sheetId = sheet.properties.sheetId;

    await sheets.spreadsheets.values.update({
      spreadsheetId: SPREADSHEET_ID,
      range: `${OUTPUT_SHEET_NAME}!A1:G1`,
      valueInputOption: 'RAW',
      resource: { values: [header] }
    });

    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: SPREADSHEET_ID,
      resource: {
        requests: [{
          updateCells: {
            range: { sheetId, startRowIndex: 1, endRowIndex: 10000 },
            fields: 'userEnteredValue'
          }
        }]
      }
    });
  }

  if (data.length > 0) {
    await sheets.spreadsheets.values.append({
      spreadsheetId: SPREADSHEET_ID,
      range: `${OUTPUT_SHEET_NAME}!A2`,
      valueInputOption: 'RAW',
      insertDataOption: 'INSERT_ROWS',
      resource: { values: data }
    });
  }
}

// ✅ EXPORTA FUNÇÃO
module.exports = async function gerarRelatorioSemanal() {
  const sheetAuth = await authenticateServiceAccount();
  const credentials = await readCredentialsFromSheet(sheetAuth);

  const sheets = google.sheets({ version: 'v4', auth: sheetAuth });

  const { monday, sunday } = getCurrentWeekRange();

  // painel: amanhã até +5 dias
  const now = new Date();
  const panelStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0);
  const panelEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 5, 23, 59, 59);

  const sheetData = [];
  const weekly = {};   // { SDR: {propostas, reunioes} }
  const byDay = {};    // { YYYY-MM-DD: { SDR: {propostas, reunioes} } }
  const falhas = [];   // [{email, motivo}]

  for (const cred of credentials) {
    const { user_email, refresh_token, client_id, client_secret } = cred;
    const sdrName = EMAIL_MAPPING[user_email] || user_email;
    weekly[sdrName] ||= { propostas: 0, reunioes: 0 };

    try {
      const oauth2Client = new google.auth.OAuth2(client_id, client_secret);
      oauth2Client.setCredentials({ refresh_token });
      const calendar = google.calendar({ version: 'v3', auth: oauth2Client });

      // ---- 1) Atualiza aba (próximos dias), só relevantes
      const panelEvents = await calendar.events.list({
        calendarId: 'primary',
        timeMin: panelStart.toISOString(),
        timeMax: panelEnd.toISOString(),
        singleEvents: true,
        orderBy: 'startTime'
      });

      const panelItems = (panelEvents.data.items || []).filter(e => isRelevantEvent(e.summary || ''));
      panelItems.forEach(event => {
        const guestEmail =
          event.attendees?.find(a => a.email && a.email.toLowerCase() !== user_email.toLowerCase())?.email || '';

        sheetData.push([
          sdrName,
          guestEmail,
          event.summary || '',
          formatDateBR(event.start.dateTime || event.start.date),
          formatDateBR(event.end.dateTime || event.end.date),
          event.description || '',
          event.location || ''
        ]);
      });

      // ---- 2) Contagem semana vigente (monday..sunday), só relevantes
      const weekEvents = await calendar.events.list({
        calendarId: 'primary',
        timeMin: monday.toISOString(),
        timeMax: sunday.toISOString(),
        singleEvents: true,
        orderBy: 'startTime'
      });

      const weekItems = (weekEvents.data.items || []).filter(e => isRelevantEvent(e.summary || ''));
      weekItems.forEach(event => {
        const start = event.start.dateTime || event.start.date;
        const dk = dayKey(start);

        byDay[dk] ||= {};
        byDay[dk][sdrName] ||= { propostas: 0, reunioes: 0 };

        if (isProposal(event.summary || '')) {
          weekly[sdrName].propostas++;
          byDay[dk][sdrName].propostas++;
        } else {
          weekly[sdrName].reunioes++;
          byDay[dk][sdrName].reunioes++;
        }
      });

    } catch (err) {
      // ✅ não derruba tudo: registra falha e continua
      falhas.push({
        email: user_email,
        motivo: err?.response?.data?.error_description || err?.message || 'Erro desconhecido'
      });
      console.error(`[reunioesSemanais] falha em ${user_email}:`, err?.message || err);
      continue;
    }
  }

  // Atualiza a planilha mesmo com falhas (com o que deu pra coletar)
  await writeToSheetClean(sheets, sheetData);

  // Monta dados para o seu HTML (data.dados)
  const dados = Object.entries(weekly)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([sdr, c]) => ({ sdr, propostas: c.propostas, reunioes: c.reunioes }));

  // Monta porDia para o CSV
  const porDia = Object.keys(byDay)
    .sort()
    .map(k => ({
      dataKey: k,
      dataBR: dayKeyToBR(k),
      dados: Object.entries(byDay[k])
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([sdr, c]) => ({ sdr, propostas: c.propostas, reunioes: c.reunioes }))
    }));

  return {
    periodo: { inicio: formatDateOnlyBR(monday), fim: formatDateOnlyBR(sunday) },
    geradoEm: new Date().toISOString(),
    dados,     // ✅ seu HTML usa data.dados
    porDia,    // ✅ usado no CSV por dia
    falhas     // ✅ pra você ver quem está com invalid_grant
  };
};
