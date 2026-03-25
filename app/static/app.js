function mailDesk() {
  const initial = JSON.parse(document.getElementById('initial-state').textContent)

  return {
    acceptedDomains: initial.acceptedDomains || ['axione.xyz'],
    pollSeconds: initial.pollSeconds,
    currentUser: initial.currentUser,
    search: '',
    composeOpen: false,
    composeError: '',
    notice: { text: '', type: 'success' },
    inboxes: [],
    messages: [],
    activeInbox: null,
    selectedMessage: null,
    selectedMessageDetail: null,
    poller: null,
    pendingUsers: [],
    filter: { mode: 'all' },
    auth: { user: initial.currentUser, mode: 'login', message: '', error: '', form: { username: '', password: '' } },
    form: { localPart: '', domain: (initial.acceptedDomains || ['axione.xyz'])[0] || 'axione.xyz', isPersistent: false, profileName: '' },

    async init() {
      await this.loadMe()
      if (this.auth.user) {
        this.ensureValidDomain()
        await this.fetchInboxes()
        if (this.auth.user.is_admin) await this.loadPendingUsers()
      }
      this.startPolling()
    },

    ensureValidDomain() {
      if (!this.acceptedDomains.length) this.acceptedDomains = ['axione.xyz']
      if (!this.acceptedDomains.includes(this.form.domain)) this.form.domain = this.acceptedDomains[0]
    },

    async api(url, options = {}) {
      const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options })
      if (!response.ok) {
        let message = 'Istek basarisiz'
        try {
          const payload = await response.json()
          message = payload.detail || payload.message || message
        } catch {
          message = await response.text() || message
        }
        if (response.status === 401) this.auth.user = null
        throw new Error(message)
      }
      if (response.status === 204) return null
      const contentType = response.headers.get('content-type') || ''
      return contentType.includes('application/json') ? response.json() : response.text()
    },

    async loadMe() {
      const payload = await this.api('/api/auth/me')
      this.auth.user = payload.user
    },

    async register() {
      this.auth.error = ''
      this.auth.message = ''
      try {
        const payload = await this.api('/api/auth/register', { method: 'POST', body: JSON.stringify(this.auth.form) })
        this.auth.message = payload.message
        this.setNotice(payload.message, 'success')
        this.auth.mode = 'login'
      } catch (error) {
        this.auth.error = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async login() {
      this.auth.error = ''
      this.auth.message = ''
      try {
        const payload = await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.auth.form) })
        this.auth.user = payload.user
        this.auth.form.password = ''
        this.ensureValidDomain()
        this.setNotice(`Hos geldin ${payload.user.username}`, 'success')
        await this.fetchInboxes()
        if (this.auth.user && this.auth.user.is_admin) await this.loadPendingUsers()
      } catch (error) {
        this.auth.error = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async logout() {
      await this.api('/api/auth/logout', { method: 'POST' })
      this.auth.user = null
      this.inboxes = []
      this.messages = []
      this.selectedMessage = null
      this.selectedMessageDetail = null
      this.composeOpen = false
      this.setNotice('Cikis yapildi', 'success')
    },

    async loadPendingUsers() {
      if (!this.auth.user || !this.auth.user.is_admin) return
      this.pendingUsers = await this.api('/api/admin/users')
    },

    async approveUser(userId) {
      await this.api(`/api/admin/users/${userId}/approve`, { method: 'POST' })
      this.setNotice('Kullanici onaylandi', 'success')
      await this.loadPendingUsers()
    },

    async fetchInboxes() {
      if (!this.auth.user) return
      this.inboxes = await this.api('/api/inboxes')
      if (!this.activeInbox && this.inboxes[0]) await this.selectInbox(this.inboxes[0].address)
      else if (this.activeInbox) {
        const fresh = this.inboxes.find((item) => item.address === this.activeInbox.address)
        if (fresh) this.activeInbox = fresh
      }
    },

    async createInbox() {
      this.ensureValidDomain()
      this.composeError = ''
      try {
        const inbox = await this.api('/api/inboxes', {
          method: 'POST',
          body: JSON.stringify({
            local_part: this.form.localPart || null,
            domain: this.form.domain || null,
            is_persistent: this.form.isPersistent,
            profile_name: this.form.profileName || null,
          }),
        })
        this.form.localPart = ''
        this.form.profileName = ''
        this.composeOpen = false
        this.setNotice(`Inbox olusturuldu: ${inbox.address}`, 'success')
        await this.fetchInboxes()
        await this.selectInbox(inbox.address)
      } catch (error) {
        this.composeError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async selectInbox(address) {
      this.activeInbox = this.inboxes.find((item) => item.address === address) || await this.api(`/api/inboxes/${encodeURIComponent(address)}`)
      await this.refreshMessages()
    },

    async refreshMessages() {
      if (!this.activeInbox || !this.auth.user) return
      this.messages = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}/messages`)
      await this.fetchInboxes()
      if (!this.messages.length) {
        this.selectedMessage = null
        this.selectedMessageDetail = null
        return
      }
      const currentId = this.selectedMessage?.id
      const nextMessage = this.messages.find((item) => item.id === currentId) || this.filteredMessages()[0] || this.messages[0]
      if (nextMessage) await this.loadMessage(nextMessage.id)
    },

    async loadMessage(messageId) {
      this.selectedMessageDetail = await this.api(`/api/messages/${messageId}`)
      this.selectedMessage = this.messages.find((item) => item.id === messageId) || this.selectedMessageDetail
      if (this.selectedMessage) this.selectedMessage.is_unread = false
      await this.fetchInboxes()
    },

    async togglePersistent() {
      if (!this.activeInbox) return
      const updated = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}`, { method: 'PATCH', body: JSON.stringify({ is_persistent: !this.activeInbox.is_persistent }) })
      this.activeInbox = updated
      await this.fetchInboxes()
    },

    async toggleSelectedUnread() {
      if (!this.selectedMessage) return
      const updated = await this.api(`/api/messages/${this.selectedMessage.id}`, { method: 'PATCH', body: JSON.stringify({ is_unread: !this.selectedMessage.is_unread }) })
      const index = this.messages.findIndex((item) => item.id === updated.id)
      if (index >= 0) this.messages[index] = { ...this.messages[index], ...updated }
      this.selectedMessage = { ...(this.selectedMessage || {}), ...updated }
      if (this.selectedMessageDetail) this.selectedMessageDetail.is_unread = updated.is_unread
      await this.fetchInboxes()
    },

    async purgeInbox() {
      if (!this.activeInbox) return
      await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}/messages`, { method: 'DELETE' })
      await this.refreshMessages()
    },

    async deleteSelectedMessage() {
      if (!this.selectedMessage) return
      await this.api(`/api/messages/${this.selectedMessage.id}`, { method: 'DELETE' })
      await this.refreshMessages()
    },

    filteredMessages() {
      let items = this.messages
      if (this.filter.mode === 'verification') items = items.filter((m) => ['verification', 'password_reset', 'login_link', 'code'].includes(m.message_kind))
      if (this.filter.mode === 'unread') items = items.filter((m) => m.is_unread)
      if (this.search.trim()) {
        const q = this.search.trim().toLowerCase()
        items = items.filter((m) => [m.subject, m.mail_from, m.sender_domain, m.summary].join(' ').toLowerCase().includes(q))
      }
      return items
    },

    totalUnread() {
      return this.inboxes.reduce((sum, inbox) => sum + (inbox.unread_count || 0), 0)
    },

    startPolling() {
      clearInterval(this.poller)
      this.poller = setInterval(() => {
        if (this.activeInbox && this.auth.user) this.refreshMessages()
        if (this.auth.user && this.auth.user.is_admin) this.loadPendingUsers()
      }, this.pollSeconds * 1000)
    },

    copyText(value) {
      navigator.clipboard.writeText(value)
    },

    openLink(value) {
      window.open(value, '_blank', 'noopener,noreferrer')
    },

    formatDate(value) {
      if (!value) return '-'
      return new Date(value).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })
    },

    messageCounterLabel() {
      const total = this.filteredMessages().length
      return total ? `1-${Math.min(total, 50)} / ${total}` : '0 mesaj'
    },

    previewInboxAddress() {
      const local = this.form.localPart?.trim() || 'otomatik-uretilecek'
      const domain = this.form.domain || this.acceptedDomains[0] || 'axione.xyz'
      return `${local}@${domain}`
    },

    setNotice(text, type = 'success') {
      this.notice = { text, type }
    },

    clearNotice() {
      this.notice = { text: '', type: 'success' }
    },
  }
}
