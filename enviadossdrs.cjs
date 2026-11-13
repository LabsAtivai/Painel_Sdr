const { google } = require('googleapis');
const fs = require('fs').promises;
const path = require('path');

// Configurações principais
const SPREADSHEET_ID = '15XBHreEoGaWl8-ctys_0Jfj1OYLWd7Koe3iN40z6Z6M'; // ID da planilha
const CREDENTIALS_SHEET_NAME = 'Credentials';
const OUTPUT_SHEET_NAME = 'enviados';
const SCOPES = [
  'https://www.googleapis.com/auth/spreadsheets', // Para leitura e escrita
  'https://www.googleapis.com/auth/gmail.readonly'
];
const SERVICE_ACCOUNT_FILE = './service-account-credentials.json'; // Caminho para o arquivo de credenciais da conta de serviço
const OUTPUT_FILE = 'resultados.txt'; // Arquivo para salvar os resultados (redundância)

// Mapeamento de e-mails do Gmail para nomes de e-mail desejados
const EMAIL_MAPPING = {
  'sdr7.ativa@gmail.com': 'Esthela@ativa.ai', 
  'sdr0.ativaai@gmail.com': 'Andrade@ativa.ai', 
  'sdr6.ativa@gmail.com': 'Leo@ativa.ai',  
  'sdr3.1.ativa@gmail.com': 'Rienzi@ativa.ai', 
  'sdr2.ativaai@gmail.com': 'Domingues@ativa.ai', 
  'sdr1.ativaai@gmail.com': 'Julia@ativa.ai', 
  'sdr9.ativa@gmail.com': 'Tura@ativa.ai',  
  'sdr4ativa@gmail.com':'Felipe@ativa.ai', 
};

// Função principal
async function main() {
  try {
    console.log('Lendo credenciais da planilha...');

    // Autenticar na API do Google Sheets usando conta de serviço
    const auth = await authenticateServiceAccount();
    const credentials = await readCredentialsFromSheet(auth);

    if (credentials.length === 0) {
      console.log('Nenhuma credencial válida encontrada na planilha.');
      return;
    }

    const results = [];
    const sheetData = [];

    // Data alvo: passe DD/MM/YYYY como argumento (node enviadossdrs.cjs 03/07/2026) ou use hoje por padrão
    const targetDateArg = process.argv[2];
    let today;
    if (targetDateArg) {
      const [d, m, y] = targetDateArg.split('/').map(Number);
      today = new Date(y, m - 1, d);
    } else {
      today = new Date();
    }

    const todayFormatted = today.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });

    // Processar cada usuário
    for (const cred of credentials) {
      try {
        const { user_email, refresh_token, client_id, client_secret } = cred;
        const sentCount = await countSentEmails({ user_email, refresh_token, client_id, client_secret, date: today });

        // Mapear o e-mail do Gmail para o nome desejado
        const mappedEmail = EMAIL_MAPPING[user_email] || user_email;
        console.log(`Total de e-mails enviados hoje (${todayFormatted}) para ${mappedEmail}: ${sentCount}`);

        // Adicionar aos resultados para o arquivo
        results.push(`Usuário: ${mappedEmail}, Total Enviados Hoje (${todayFormatted}): ${sentCount}`);

        // Adicionar aos dados para a planilha
        sheetData.push([todayFormatted, mappedEmail, sentCount]);
      } catch (error) {
        console.error(`Erro ao processar ${cred.user_email}: ${error.message}`);
      }
    }

    // Escrever resultados na planilha
    await writeResultsToSheet(auth, sheetData);

    // Salvar resultados em arquivo (mantido para redundância)
    await saveResultsToFile(results);
    console.log(`Resultados salvos em ${OUTPUT_FILE} e na aba ${OUTPUT_SHEET_NAME} da planilha`);

  } catch (error) {
    console.error('Erro na execução principal:', error.message);
  }
}

// Autenticar usando a conta de serviço
async function authenticateServiceAccount() {
  const auth = new google.auth.GoogleAuth({
    keyFile: SERVICE_ACCOUNT_FILE,
    scopes: SCOPES
  });
  return await auth.getClient();
}

// Ler credenciais da planilha
async function readCredentialsFromSheet(auth) {
  const sheets = google.sheets({ version: 'v4', auth });
  try {
    const response = await sheets.spreadsheets.values.get({
      spreadsheetId: SPREADSHEET_ID,
      range: `${CREDENTIALS_SHEET_NAME}!A:D`
    });

    const rows = response.data.values || [];
    console.log('Linhas brutas lidas da planilha:', rows);

    if (rows.length <= 1) {
      console.log('Planilha vazia ou contém apenas o cabeçalho.');
      return [];
    }

    // Mapear as linhas para objetos de credenciais (ignorando o cabeçalho)
    const credentials = rows.slice(1).map((row, index) => {
      const cred = {
        user_email: row[0] ? row[0].trim() : '',
        refresh_token: row[1] ? row[1].trim() : '',
        client_id: row[2] ? row[2].trim() : '',
        client_secret: row[3] ? row[3].trim() : ''
      };
      console.log(`Linha ${index + 2}:`, cred); // Log para depuração
      return cred;
    });

    // Filtrar credenciais válidas
    const validCredentials = credentials.filter(cred => {
      const isValid = cred.user_email && cred.refresh_token && cred.client_id && cred.client_secret;
      if (!isValid) {
        console.log(`Linha descartada (dados incompletos):`, cred);
      }
      return isValid;
    });

    console.log('Credenciais válidas encontradas:', validCredentials);
    return validCredentials;
  } catch (error) {
    throw new Error(`Erro ao ler a planilha: ${error.message}`);
  }
}

// Contar e-mails enviados para um usuário (apenas os enviados hoje)
async function countSentEmails({ user_email, refresh_token, client_id, client_secret, date }) {
  try {
    // Configurar autenticação OAuth para o Gmail
    const oauth2Client = new google.auth.OAuth2(client_id, client_secret);
    oauth2Client.setCredentials({ refresh_token });

    const gmail = google.gmail({ version: 'v1', auth: oauth2Client });

    // Formatar a data para o formato YYYY/MM/DD exigido pela API do Gmail
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0'); // Mês começa em 0, então +1
    const day = String(date.getDate()).padStart(2, '0');
    const dateFilter = `${year}/${month}/${day}`;

    // Dia seguinte, para limitar a busca apenas ao dia alvo (evita contar dias posteriores)
    const nextDay = new Date(date);
    nextDay.setDate(nextDay.getDate() + 1);
    const nextDateFilter = `${nextDay.getFullYear()}/${String(nextDay.getMonth() + 1).padStart(2, '0')}/${String(nextDay.getDate()).padStart(2, '0')}`;

    let totalMessages = 0;
    let nextPageToken = null;

    // Paginação para listar todas as mensagens enviadas no dia alvo
    do {
      const response = await gmail.users.messages.list({
        userId: 'me',
        labelIds: ['SENT'],
        q: `after:${dateFilter} before:${nextDateFilter}`, // Filtra mensagens enviadas apenas no dia alvo
        pageToken: nextPageToken,
        maxResults: 500 // Máximo permitido por chamada
      });

      const messages = response.data.messages || [];
      totalMessages += messages.length;
      nextPageToken = response.data.nextPageToken;
    } while (nextPageToken);

    return totalMessages;
  } catch (error) {
    if (error.code === 401 || error.code === 403) {
      throw new Error('Credenciais inválidas ou refresh token expirado');
    } else if (error.code === 429) {
      throw new Error('Limite de cota da API atingido');
    }
    throw new Error(`Erro ao contar e-mails: ${error.message}`);
  }
}

// Escrever resultados na aba "enviados" da planilha
async function writeResultsToSheet(auth, sheetData) {
  const sheets = google.sheets({ version: 'v4', auth });
  try {
    // Verificar se a aba "enviados" existe, senão criar
    const spreadsheet = await sheets.spreadsheets.get({
      spreadsheetId: SPREADSHEET_ID
    });
    const sheetExists = spreadsheet.data.sheets.some(sheet => sheet.properties.title === OUTPUT_SHEET_NAME);

    if (!sheetExists) {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId: SPREADSHEET_ID,
        resource: {
          requests: [{
            addSheet: {
              properties: {
                title: OUTPUT_SHEET_NAME
              }
            }
          }]
        }
      });
    }

    // Adicionar cabeçalho se a aba estiver vazia
    const range = `${OUTPUT_SHEET_NAME}!A:C`;
    const existingData = await sheets.spreadsheets.values.get({
      spreadsheetId: SPREADSHEET_ID,
      range
    }).catch(() => ({ data: { values: [] } }));

    const values = existingData.data.values || [];
    if (values.length === 0) {
      values.push(['Data', 'emails', 'enviados']); // Cabeçalho
    }

    // Adicionar novos dados
    values.push(...sheetData);

    // Escrever na planilha
    await sheets.spreadsheets.values.update({
      spreadsheetId: SPREADSHEET_ID,
      range,
      valueInputOption: 'RAW',
      resource: { values }
    });

    console.log(`Resultados escritos na aba ${OUTPUT_SHEET_NAME}`);
  } catch (error) {
    throw new Error(`Erro ao escrever na planilha: ${error.message}`);
  }
}

// Salvar resultados em arquivo (mantido para redundância)
async function saveResultsToFile(results) {
  try {
    await fs.writeFile(OUTPUT_FILE, results.join('\n') + '\n');
  } catch (error) {
    console.error(`Erro ao salvar resultados no arquivo: ${error.message}`);
  }
}

// Executar o script
main().catch(console.error);
