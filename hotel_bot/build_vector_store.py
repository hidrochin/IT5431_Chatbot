import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

def build_knowledge_base():
    # 1. Load the PDF
    loader = PyPDFLoader("data/knowledge_base/hotel_policies.pdf")
    pages = loader.load()
    full_text = "\n".join([page.page_content for page in pages])

    # 2. Strict Intra-Region Parsing
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", ".", " "]
    )
    
    chunks = text_splitter.create_documents([full_text])
    print(f"Generated {len(chunks)} localized policy chunks.")

    # 3. Generate Embeddings using BGE-M3 (Running Locally)
    print("Downloading and loading BGE-M3 model... (This may take a moment on the first run)")
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={'device': 'cpu'}, # Change to 'cuda' if you have an Nvidia GPU setup
        encode_kwargs={'normalize_embeddings': True} 
    )
    
    # 4. Store in FAISS
    print("Building FAISS vector index...")
    vector_store = FAISS.from_documents(chunks, embeddings)
    
    # Save the local database
    os.makedirs("db/faiss_index", exist_ok=True)
    vector_store.save_local("db/faiss_index")
    print("Vector database successfully built and saved to db/faiss_index/")

if __name__ == "__main__":
    build_knowledge_base()