const { google } = require('googleapis');
const fs = require('fs');

// Configurações principais
const SPREADSHEET_ID = '15XBHreEoGaWl8-ctys_0Jfj1OYLWd7Koe3iN40z6Z6M';
const CREDENTIALS_SHEET_NAME = 'Credentials';
const OUTPUT_SHEET_NAME = 'Reunioes do Dia Seguinte';
const SERVICE_ACCOUNT_FILE = './service-account-credentials.json';

const EMAIL_MAPPING = {
  'sdr7.ativa@gmail.com': 'Esthela', 
  'sdr0.ativaai@gmail.com': 'Andrade', 
  'sdr6.ativa@gmail.com': 'Leo',  
  'sdr3.1.ativa@gmail.com': 'Rienzi', 
  'sdr2.ativaai@gmail.com': 'Domingues', 
  'sdr1.ativaai@gmail.com': 'Julia', 
  'sdr9.ativa@gmail.com': 'Tura',  
  'sdr4ativa@gmail.com':'Taina',

};

function formatDateBR(dateString) {
  const date = new Date(dateString);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

async function main() {
  const sheetAuth = await authenticateServiceAccount();
  const credentials = await readCredentialsFromSheet(sheetAuth);

  if (credentials.length === 0) {
    console.log('Nenhuma credencial válida encontrada na planilha.');
    return;
  }

  const sheet = google.sheets({ version: 'v4', auth: sheetAuth });
  const sheetData = [];

  const now = new Date();
  const tomorrowStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 0, 0, 0, 0);
  const tomorrowEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 0, 23, 59, 59);

  for (const cred of credentials) {
    const { user_email, refresh_token, client_id, client_secret } = cred;
    const mappedName = EMAIL_MAPPING[user_email] || user_email;

    try {
      const oauth2Client = new google.auth.OAuth2(client_id, client_secret);
      oauth2Client.setCredentials({ refresh_token });

      const calendar = google.calendar({ version: 'v3', auth: oauth2Client });
      const events = await calendar.events.list({
        calendarId: 'primary',
        timeMin: tomorrowStart.toISOString(),
        timeMax: tomorrowEnd.toISOString(),
        singleEvents: true,
        orderBy: 'startTime'
      });

      const items = events.data.items || [];
      items.forEach(event => {
        const guestEmail = event.attendees?.[0]?.email || '';
        sheetData.push([
          mappedName,
          guestEmail,
          event.summary || '',
          formatDateBR(event.start.dateTime || event.start.date),
          formatDateBR(event.end.dateTime || event.end.date),
          event.description || '',
          event.location || ''
        ]);

      });

      console.log(`Reuniões adicionadas para ${mappedName}: ${items.length}`);
    } catch (error) {
      console.error(`Erro ao processar ${user_email}: ${error.message}`);
    }
  }

  await writeToSheet(sheet, sheetData);
  console.log('Todas as reuniões do dia seguinte foram adicionadas.');
}

// Autenticação via conta de serviço para acessar a planilha
async function authenticateServiceAccount() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: ['https://www.googleapis.com/auth/spreadsheets']
  });
  return auth.getClient();
}

// Ler credenciais da aba 'Credentials' da planilha
async function readCredentialsFromSheet(auth) {
  const sheets = google.sheets({ version: 'v4', auth });
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range: `${CREDENTIALS_SHEET_NAME}!A:D`
  });

  const rows = response.data.values || [];
  if (rows.length <= 1) return [];

  return rows.slice(1).map(row => ({
    user_email: row[0]?.trim() || '',
    refresh_token: row[1]?.trim() || '',
    client_id: row[2]?.trim() || '',
    client_secret: row[3]?.trim() || ''
  })).filter(cred =>
    cred.user_email && cred.refresh_token && cred.client_id && cred.client_secret
  );
}

// Escrever os dados na planilha
async function writeToSheet(sheets, data) {
  const spreadsheet = await sheets.spreadsheets.get({ spreadsheetId: SPREADSHEET_ID });
  const exists = spreadsheet.data.sheets.some(s => s.properties.title === OUTPUT_SHEET_NAME);

  if (!exists) {
    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: SPREADSHEET_ID,
      resource: {
        requests: [{ addSheet: { properties: { title: OUTPUT_SHEET_NAME } } }]
      }
    });
  }

  await sheets.spreadsheets.values.append({
    spreadsheetId: SPREADSHEET_ID,
    range: OUTPUT_SHEET_NAME,
    valueInputOption: 'RAW',
    insertDataOption: 'INSERT_ROWS',
    resource: { values: data }
  });
}

main().catch(console.error);
