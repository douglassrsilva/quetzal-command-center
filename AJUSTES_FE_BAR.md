# Quetzal — roteiro de ajustes e continuação

Base: auditoria realizada em 11/10/2026 e instruções consultadas no Skills Navigator, nas abas Getting started e Submission - Build.

Objetivo: fechar as lacunas técnicas e de entrega do Quetzal, preservando a aplicação existente, e preparar uma submissão verificável ao FE Bar. Este roteiro não é uma aprovação oficial.

## 1. Contexto que deve ser preservado

- Aplicação local/publicada: `VibeCodingApps/Quetzal`.
- Pacote versionado de entrega: `VibeCodingApps/quetzal-customer-kit`.
- A pasta Quetzal não é um repositório Git. O Customer Kit é; sua revisão local e a revisão do GitHub coincidiam na auditoria.
- O app estava ativo. Os hashes de `app.py` e `server/operations.py` locais correspondiam ao snapshot publicado.
- O workspace contém um pipeline Lakeflow concluído e modelos ML reais. Seus fontes completos não estão no kit auditado.
- O Lakebase está conectado e implementa histórico conversacional do Quetzal IQ.
- Os três espaços Genie existem; foi encontrada resposta histórica real com SQL e resultados rastreáveis.
- Passaram 51 testes do app, 55 do kit, TypeScript, build do frontend, lint do kit e sanitização.
- O preflight estava `DEGRADED`: grafo `graph-fusion-v1` e triplas OntoBricks ausentes.
- No teste com 1.000 clientes do Panamá e premissas padrão, o impacto líquido foi −US$ 5.828,97 e o ROI −72,9%. É uma estimativa contrafactual, não um resultado observado.

Estes são resultados datados, não garantias sobre o estado futuro. Revalidar antes de promover uma nova versão.

## 2. Limites de execução

Continuar nesta mesma sessão, aproveitando o contexto, perfis e abas existentes. Não recriar o projeto, revogar credenciais ou iniciar login novamente sem necessidade comprovada.

Ao implementar:

- Preservar alterações do usuário; verificar o estado do Git antes de editar o kit.
- Fazer mudanças pequenas e revisáveis. Não sincronizar as duas pastas indiscriminadamente.
- Manter a configuração parametrizada e sanitizada do kit; não copiar para ele hosts, IDs ou usuários do ambiente de origem.
- Usar DAB como fonte de verdade de recursos e implantação. Não terminar a entrega com sync manual.
- Preservar OAuth gerenciado, o ledger Lakebase e a memória existente. Não substituir credenciais temporárias por tokens estáticos.
- Manter jobs exclusivamente manuais, conectores desabilitados e aprovação humana para ações.
- Não executar treinamento, pipelines, bootstrap, refresh de grafo, inferências novas, migrações remotas, deploy, push ou submissão do FE Bar sem autorização para a respectiva etapa.
- Não sobrescrever tabelas ou modelos existentes para produzir evidência.
- Não apresentar fixtures, regras sintéticas ou outputs esperados como execução real.

## 3. Ordem de implementação e critérios de aceite

### Etapa A — Governança e identidade

Arquivos principais: `server/operations.py`, `app.py`, `server/platform.py`, `server/config.py`, `resources/app.yml` e testes.

1. Separar explicitamente execução local/testes da execução publicada.
2. Eliminar o fallback administrativo quando a identidade estiver ausente no ambiente publicado. Falhar fechado, sem consultas ou ações privilegiadas.
3. Centralizar a resolução de identidade, papéis e alcance territorial.
4. Revisar APIs operacionais, KPIs, relatórios, ferramentas do Quetzal IQ, Genie e acesso a conversas. Aplicar a política de autorização em todos os caminhos relevantes.
5. Considerar a identidade efetiva usada nas consultas: declarar escopos de usuário no App não prova, sozinho, que as consultas usam essa identidade.
6. Garantir isolamento de cache por escopo autorizado, sem reutilização de resultados entre territórios ou usuários incompatíveis.
7. Preservar segregação entre solicitante e aprovador. Rever permissões do App e grants com menor privilégio, sem mudanças remotas automáticas.
8. Testar com perfis sintéticos distintos, não somente com administrador.

Aceite:

- Sem identidade válida, o ambiente publicado não concede ADMIN.
- Usuário sem papel apropriado não executa operações restritas.
- Consultas, ferramentas de IA e resultados obedecem ao escopo autorizado.
- Um usuário não recupera histórico de outro.
- Os testes locais usam identidade explícita ou um modo local controlado, sem enfraquecer a configuração publicada.

### Etapa B — Empacotar o Lakeflow e o ML reais

Arquivos principais: novas pastas de fontes Lakeflow/ML no kit, `resources/`, `databricks.yml`, notebooks de geração e documentação.

1. Recuperar por leitura os fontes existentes de Bronze, Silver, Gold, treinamento e scoring do workspace.
2. Parametrizar catálogo, schema, volume, caminhos e recursos; sanitizar antes de adicionar ao kit.
3. Versionar o pipeline Lakeflow no bundle, incluindo ingestão raw, transformações e regras de qualidade. Um job Spark que cria diretamente tabelas Silver/Gold não deve ser apresentado como esse pipeline.
4. Incluir treinamento, avaliação e registro MLflow, além do scoring que alimenta as tabelas consumidas pelo App e Genie.
5. Separar geração de dados sintéticos da geração de previsões por modelo. Hoje o kit copia `churn_risk_score` para `churn_probability`.
6. Manter a regra sintética apenas como modo demonstrativo explicitamente identificado, se ainda for útil. Não rotulá-la como modelo treinado.
7. Documentar datasets, alvo, horizonte de previsão, features, split, limitações e diferenças entre a base original e a base menor do kit.
8. Verificar temporalidade e possíveis sinais posteriores ao evento de churn. Métricas altas em dados sintéticos não comprovam desempenho em produção.
9. Fazer importação e validação local dos fontes sem executar automaticamente treinamento ou pipeline.

Aceite:

- O kit contém os fontes necessários para reconstruir o fluxo raw → Lakeflow → tabelas UC → inteligência → consumidores.
- Os consumidores apontam para os produtos de dados corretos.
- Há distinção inequívoca entre score heurístico e previsão de um modelo.
- Métricas e outputs são atribuídos à execução e ao dataset que realmente os produziram.
- Execuções existentes podem fornecer evidência; repetir processamento não é obrigatório só para coletá-la.

Nota de escopo: o requisito geral é ML **ou** GenAI. Modelo treinado **e servido em endpoint** é uma exigência adicional da rota AI Customer Challenge. Não impor essa rota ao Quetzal sem confirmar sua origem e a opção de submissão escolhida.

### Etapa C — Comprovar o papel operacional do Lakebase

Arquivos principais: `server/memory.py`, backend operacional, recursos Lakebase, testes e roteiro de demonstração.

1. Mapear uma mesma entidade ou decisão desde os dados UC até a inteligência, a aplicação e a persistência operacional.
2. Primeiro verificar se o uso atual do histórico de IA demonstra suficientemente esse papel. Documentar a ligação entre resposta, evidência, usuário e decisão de negócio.
3. Se isso não bastar, propor uma extensão pequena: por exemplo, um caso de retenção persistido no Lakebase, ligado ao cliente sintético e à versão do score.
4. Antes de implementar a extensão, definir a fonte de verdade de cada estado. Não duplicar o mesmo estado operacional em Delta e Postgres com gravações independentes.
5. Para qualquer novo fluxo, definir transições, idempotência, autoria, aprovação e comportamento quando o Lakebase estiver indisponível.
6. Preferir migrações aditivas e compatíveis. Nenhuma migração ou teste de escrita remoto será executado sem autorização.

Aceite:

- A narrativa mostra concretamente o papel operacional do Lakebase na mesma jornada de negócio.
- Persistência, recuperação e isolamento são testados.
- Indisponibilidade não é apresentada como sucesso nem resulta em uma ação silenciosamente perdida.
- Conversas e memória existentes continuam funcionando.

Esta etapa é uma recomendação para fechar a lacuna de comprovação. As instruções consultadas não obrigam copiar todas as tabelas de clientes para o Lakebase.

### Etapa D — Jornada e modelo econômico

Arquivos principais: `server/operations.py`, `server/models.py`, `frontend/src/DemoJourneyPage.tsx`, `CommercialIntelligencePages.tsx` e `DEMO.md`.

1. Conectar os exemplos escolhidos no roteiro a uma população coerente e elegível para o objetivo demonstrado.
2. Quando o simulador se referir a uma campanha, usar sua população elegível e as mesmas premissas, em vez de misturar a média de um país com um público priorizado diferente.
3. Explicitar horizonte e significado da probabilidade de churn. Não tratar um score sem horizonte definido como taxa anual.
4. Mostrar custos, benefício estimado, impacto líquido, sensibilidade e ponto de equilíbrio. Identificar limitações e custos ainda não incluídos.
5. Preservar e explicar resultados negativos. Não ajustar taxas arbitrariamente para tornar o ROI positivo.
6. Manter as etiquetas de estimativa contrafactual, dados sintéticos e ausência de causalidade.
7. Não afirmar vínculo torre–cliente onde só existe contexto geográfico.
8. Exibir versão, frescor e disponibilidade dos sinais; não descrever política v3 como ativa quando o snapshot é v1.

Aceite:

- Os números da tela, API e apresentação reconciliam para a mesma população e premissas.
- Resultados positivos, negativos e casos de fronteira têm testes.
- O roteiro explica o que foi observado, o que foi calculado e o que é apenas hipótese.

### Etapa E — Grafo v3 e OntoBricks, opcional

1. Manter o snapshot legado identificado e o estado pendente visível.
2. Se necessário para a entrega pretendida, solicitar autorização específica para custo e execução do refresh v3.
3. Após a execução autorizada, validar qualidade, volumes, versão publicada, preservação do churn individual e tabela de triplas.
4. Só configurar uma URL de App OntoBricks quando o App e o domínio realmente existirem.
5. Atualizar README e TASKS para distinguir código disponível, recurso publicado e validação concluída.

Aceite: ou os extras estão funcionando com evidência, ou são descritos honestamente como opcionais e pendentes. Não são hard gates universais do FE Bar.

### Etapa F — Evidências e apresentação

Destino recomendado no kit: `docs/fe-bar/` e `evidence/fe-bar/`.

1. Criar uma matriz requisito → fonte → teste → output real → limitação.
2. Registrar os resultados reais dos testes, pipeline, métricas MLflow, consultas, Genie e APIs em JSON, TXT, MD ou notebooks com outputs textuais.
3. Incluir data, revisão de código e referências sanitizadas que permitam rastrear cada execução. Não editar resultados para fazê-los parecer bem-sucedidos.
4. Separar evidências da aplicação original das evidências do kit. Não atribuir ao kit de 10 mil clientes métricas de uma execução com 1 milhão.
5. Usar screenshots apenas como complemento: o avaliador descrito nas instruções lê texto.
6. Documentar decisões, alternativas, trade-offs e uso de ferramentas de IA. Não criar conteúdo para manipular o avaliador.
7. Preparar um deck PDF, TXT ou MD com problema telecom, duas personas, jornada, KPIs, arquitetura, governança, custos, hipóteses e limitações.
8. Fazer sanitização e revisão de todos os artefatos, incluindo arquivos que o scanner local não cobre.
9. Na submissão, informar o GitHub e selecionar a pasta local completa. A aba consultada informa que o build é pontuado a partir dessa pasta.
10. Deixar certificação, roleplay e assinatura de atestação sob responsabilidade do usuário. Não enviar a avaliação ou atestar autoria automaticamente.

Aceite:

- Os requisitos relevantes têm fontes e evidência textual suficiente, sem depender só de imagens.
- O deck está pronto para anexar, com valor quantitativo defensável.
- A autoria e o entendimento são demonstráveis; uso de IA não substitui a responsabilidade pelas decisões.

## 4. Validação antes de publicar

Os comandos abaixo são para execução posterior, durante a implementação. Não fazem deploy nem executam jobs Databricks.

No Customer Kit:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with-requirements requirements-dev.txt python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with-requirements requirements-dev.txt ruff check app.py server tests scripts
python3 scripts/sanitize_check.py
```

No frontend de cada variante alterada:

```bash
npm run build
```

Além dos testes já existentes, incluir cobertura para identidade ausente, papéis, território, isolamento de histórico/cache, origem do score, jornada integrada, persistência operacional e reconciliação financeira.

Validar a UI local no navegador: desktop/mobile, temas claro/escuro, console, estados de erro e restrições por papel. O build do frontend, sozinho, não comprova funcionamento visual.

Validar o bundle com o perfil e variáveis corretos. O kit usa seu fluxo `scripts/bundle.sh`/Makefile; não trocar esse fluxo pelo comando do bundle original. Revisar previamente qualquer renderização de arquivos gerados.

## 5. Publicação e fechamento, somente após autorização

1. Revisar diff, testes, artefatos, migrações e plano de rollback.
2. Selecionar explicitamente qual bundle e target serão publicados. Não confundir `demo` do app original com `dev/staging/prod` do kit.
3. Publicar primeiro no ambiente de validação autorizado, usando DAB.
4. Executar somente os jobs ou migrações necessários e aprovados.
5. Revalidar saúde, preflight, jornada, Cliente 360, VOC, draft, cálculo financeiro e UI.
6. Distinguir metadata/configuração de execução: `READY` do AI Gateway no preflight atual não prova uma inferência bem-sucedida.
7. Se for necessário um novo teste real de IA/Genie, autorizar custo e persistência de conversas antes.
8. Produzir evidência textual sanitizada e revisar o pacote exato da submissão.
9. Atualizar o checklist com o que realmente foi concluído, sem marcar uma etapa inteira quando só a API foi testada.

Não exigir novo endpoint ML, grafo v3 ou App OntoBricks apenas para adicionar recursos ao build. Priorizar integração, segurança, evidência e clareza.

## 6. Ponto de continuação desta sessão

Estado deste pedido: roteiro criado; nenhuma correção de código ou publicação executada.

Próximo bloco recomendado: Etapa A, governança local, com testes de regressão e alterações equivalentes no app original e no kit, preservando as diferenças de configuração.

Ao receber autorização para implementar:

> Continue nesta mesma sessão a partir de AJUSTES_FE_BAR.md. Comece pela Etapa A e apresente os resultados locais antes de avançar. Preserve o app publicado e a configuração sanitizada do Customer Kit. Não execute deploy, push, migração remota, treinamento, pipeline, refresh de grafo, nova inferência ou submissão do FE Bar sem autorização para essa etapa. Não crie métricas ou outputs fictícios como evidência. Diferencie requisito confirmado, recomendação e funcionalidade opcional.

