const form = document.getElementById('compare-form');
const url1Input = document.getElementById('url1');
const url2Input = document.getElementById('url2');
const loadingIndicator = document.getElementById('loading-indicator');
const resultsSection = document.getElementById('comparison-results');
const tableHeaders = document.getElementById('table-headers');
const tableBody = document.getElementById('comparison-table-body');
const modal = document.getElementById('modal');
const modalMessage = document.getElementById('modal-message');
const modalCloseBtn = document.getElementById('modal-close-btn');

const API_BASE_URL = 'https://flash-compare.onrender.com';

function showModal(message) {
    modalMessage.textContent = message;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

modalCloseBtn.addEventListener('click', () => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
});

modal.addEventListener('click', (e) => {
    if (e.target === modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
});

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const url1 = url1Input.value.trim();
    const url2 = url2Input.value.trim();

    if (!url1 || !url2) {
        showModal('Please enter both URLs to compare.');
        return;
    }

    if (!isValidUrl(url1) || !isValidUrl(url2)) {
        showModal('Please enter valid URLs (must start with http:// or https://).');
        return;
    }

    loadingIndicator.classList.remove('hidden');
    resultsSection.classList.add('hidden');
    tableBody.innerHTML = '';

    try {
        const response = await fetch(`${API_BASE_URL}/compare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url1, url2 })
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            const errorMsg = typeof data.error === 'object' 
                ? JSON.stringify(data.error, null, 2) 
                : (data.error || 'An error occurred while processing the request.');
            showModal(errorMsg);
        } else {
            displayResults(data);
        }
    } catch (error) {
        console.error('Error fetching data:', error);
        showModal('A network error occurred. Please check if the backend is running on http://localhost:5000 and try again.');
    } finally {
        loadingIndicator.classList.add('hidden');
    }
});

function isValidUrl(string) {
    try {
        new URL(string);
        return string.startsWith('http://') || string.startsWith('https://');
    } catch (_) {
        return false;
    }
}

function displayResults(data) {
    resultsSection.classList.remove('hidden');

    const product1 = data.data1['Product'] || 'Item 1';
    const product2 = data.data2['Product'] || 'Item 2';

    tableHeaders.innerHTML = `
        <tr>
            <th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 uppercase">Feature</th>
            <th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 uppercase">${escapeHtml(product1)}</th>
            <th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 uppercase">${escapeHtml(product2)}</th>
        </tr>
    `;

    const keys = ['Description', 'Features', 'Price'];

    keys.forEach(key => {
        const value1 = data.data1[key];
        const value2 = data.data2[key];
        
        const row = document.createElement('tr');
        row.classList.add('hover:bg-gray-50', 'transition-colors', 'duration-200');
        
        const featureCell = document.createElement('td');
        featureCell.className = 'px-6 py-4 text-sm font-medium text-gray-900';
        featureCell.textContent = key;
        
        const cell1 = document.createElement('td');
        cell1.className = 'px-6 py-4 text-sm text-gray-900';
        cell1.innerHTML = formatValue(value1);
        
        const cell2 = document.createElement('td');
        cell2.className = 'px-6 py-4 text-sm text-gray-900';
        cell2.innerHTML = formatValue(value2);
        
        row.appendChild(featureCell);
        row.appendChild(cell1);
        row.appendChild(cell2);
        tableBody.appendChild(row);
    });

    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

function formatValue(value) {
    if (!value || value === 'N/A' || value === 'No description found' || value === 'No features found' || value === 'No price found') {
        return '<span class="text-gray-400 italic">Not available</span>';
    }
    
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return '<span class="text-gray-400 italic">Not available</span>';
        }
        const items = value.map(item => `<li class="ml-4">${escapeHtml(item)}</li>`).join('');
        return `<ul class="list-disc space-y-1">${items}</ul>`;
    }
    
    return escapeHtml(String(value));
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);

}
